import os
import unittest


os.environ["GAME_BACKEND"] = "memory"
os.environ["SECRET_KEY"] = "test-only-secret"

import app as route_app


class MultiplayerFlowTest(unittest.TestCase):
    def test_two_players_finish_and_rematch(self):
        host = route_app.app.test_client()
        guest = route_app.app.test_client()

        created = host.post("/games", data={
            "nickname": "Host",
            "route_count": "3",
            "modes": ["bus", "tram"],
            "zones": list(route_app.HSL_ZONES),
            "include_night_routes": "1",
            "include_alternative_routes": "1",
            "include_lahibussi_routes": "1",
        })
        self.assertEqual(created.status_code, 302)
        game_url = created.headers["Location"]
        game_id = game_url.rstrip("/").split("/")[-1]

        invitation = guest.get(game_url)
        self.assertEqual(invitation.status_code, 200)
        self.assertIn(b"Host", invitation.data)
        joined = guest.post(f"/games/{game_id}/join", data={"nickname": "Guest"})
        self.assertEqual(joined.status_code, 302)
        self.assertEqual(host.get(f"/games/{game_id}/state").json["status"], "playing")

        game = route_app.get_game(game_id)
        for round_number, route in enumerate(game["routes"]):
            host_state = host.post(f"/games/{game_id}/guess", data={"guess": route}).json
            self.assertEqual(host_state["round"], round_number)
            self.assertTrue(host_state["has_guessed"])
            wrong_choice = next(
                option for option in game["round_options"][round_number] if option != route
            )
            guest_state = guest.post(
                f"/games/{game_id}/guess", data={"guess": wrong_choice}
            ).json
            self.assertEqual(guest_state["round"], round_number + 1)

        self.assertEqual(guest_state["status"], "finished")
        results = host.get(f"/games/{game_id}/results")
        self.assertEqual(results.status_code, 200)
        self.assertIn(b"3", results.data)

        replay = host.post(f"/games/{game_id}/rematch")
        self.assertEqual(replay.status_code, 302)
        requested_game = route_app.get_game(game_id)
        self.assertIsNone(requested_game["rematch_id"])
        self.assertEqual(requested_game["rematch_status"], "pending")
        self.assertEqual(requested_game["rematch_requested_by"], "host")
        guest_state = guest.get(f"/games/{game_id}/state").json
        self.assertTrue(guest_state["rematch_requested_by_opponent"])
        invitation = guest.get(f"/games/{game_id}/results")
        self.assertIn(b"haluaa pelata uudelleen", invitation.data)
        self.assertIn(b"Hyv\xc3\xa4ksy", invitation.data)
        self.assertIn(b"Kielt\xc3\xa4ydy", invitation.data)

        accepted = guest.post(f"/games/{game_id}/rematch/accept")
        self.assertEqual(accepted.status_code, 302)
        rematch_id = route_app.get_game(game_id)["rematch_id"]
        self.assertTrue(rematch_id)
        self.assertEqual(route_app.get_game(rematch_id)["zones"], list(route_app.HSL_ZONES))
        self.assertEqual(guest.get(f"/games/{rematch_id}/play").status_code, 200)

    def test_rematch_can_be_declined(self):
        host = route_app.app.test_client()
        guest = route_app.app.test_client()
        created = host.post("/games", data={
            "nickname": "Host",
            "route_count": "3",
            "modes": ["bus"],
            "zones": list(route_app.HSL_ZONES),
        })
        game_id = created.headers["Location"].rstrip("/").split("/")[-1]
        guest.get(f"/games/{game_id}")
        guest.post(f"/games/{game_id}/join", data={"nickname": "Guest"})
        route_app.game_store.update(
            game_id, lambda game: game.update({"status": "finished"})
        )

        host.post(f"/games/{game_id}/rematch")
        declined = guest.post(f"/games/{game_id}/rematch/decline")

        self.assertEqual(declined.status_code, 302)
        self.assertEqual(declined.headers["Location"], "/")
        game = route_app.get_game(game_id)
        self.assertEqual(game["rematch_status"], "declined")
        self.assertIsNone(game["rematch_id"])
        host_state = host.get(f"/games/{game_id}/state").json
        self.assertEqual(host_state["rematch_status"], "declined")
        self.assertEqual(host.get(f"/games/{game_id}/results").headers["Location"], "/")

    def test_hsl_extended_route_types_cover_every_mode(self):
        for mode in route_app.MODE_LABELS:
            self.assertGreater(len(route_app.lines[route_app.lines["mode"] == mode]), 0, mode)

    def test_route_options_only_include_selected_modes(self):
        tram_options = route_app.route_options(["tram"])
        self.assertGreater(len(tram_options), 0)
        self.assertTrue(all(route_app.lines.loc[route, "mode"] == "tram" for route in tram_options))
        self.assertTrue(set(tram_options).isdisjoint(route_app.route_options(["bus"])))

    def test_each_round_has_four_choices_and_a_same_mode_distractor(self):
        game_content = route_app.choose_game_routes(
            8, ["bus", "tram", "train"], zones=list(route_app.HSL_ZONES)
        )

        self.assertIsNotNone(game_content)
        routes, choices_by_round = game_content
        self.assertEqual(len(choices_by_round), len(routes))
        for route, choices in zip(routes, choices_by_round):
            self.assertEqual(len(choices), 4)
            self.assertEqual(len(set(choices)), 4)
            self.assertIn(route, choices)
            route_mode = route_app.lines.loc[route, "mode"]
            self.assertTrue(any(
                choice != route and route_app.lines.loc[choice, "mode"] == route_mode
                for choice in choices
            ))

    def test_multiplayer_players_receive_the_same_round_options(self):
        host = route_app.app.test_client()
        guest = route_app.app.test_client()
        created = host.post("/games", data={
            "nickname": "Host",
            "route_count": "3",
            "modes": ["bus", "train"],
            "zones": list(route_app.HSL_ZONES),
        })
        game_id = created.headers["Location"].rstrip("/").split("/")[-1]
        guest.get(f"/games/{game_id}")
        guest.post(f"/games/{game_id}/join", data={"nickname": "Guest"})

        host_state = host.get(f"/games/{game_id}/state").json
        guest_state = guest.get(f"/games/{game_id}/state").json
        self.assertEqual(host_state["options"], guest_state["options"])
        self.assertEqual(len(host_state["options"]), 4)

    def test_ferry_routes_are_available_as_a_mode(self):
        ferry_options = route_app.route_options(["ferry"])
        self.assertEqual(set(ferry_options), {"17", "19", "19E"})

    def test_zone_filter_only_allows_routes_within_selected_zones(self):
        zone_a_options = route_app.route_options(list(route_app.MODE_LABELS), zones=["A"])
        zone_ab_options = route_app.route_options(
            list(route_app.MODE_LABELS), zones=["A", "B"]
        )

        self.assertGreater(len(zone_a_options), 0)
        self.assertTrue(set(zone_a_options).issubset(zone_ab_options))
        self.assertTrue(all(
            set(route_app.lines.loc[route, "zones"]).issubset({"A"})
            for route in zone_a_options
        ))
        self.assertTrue(all(
            set(route_app.lines.loc[route, "zones"]).issubset({"A", "B"})
            for route in zone_ab_options
        ))
        self.assertTrue(any(
            "B" in route_app.lines.loc[route, "zones"] for route in zone_ab_options
        ))

    def test_special_routes_can_be_excluded(self):
        all_options = route_app.route_options(list(route_app.MODE_LABELS))
        filtered_options = route_app.route_options(
            list(route_app.MODE_LABELS),
            include_night_routes=False,
            include_alternative_routes=False,
            include_lahibussi_routes=False,
        )

        self.assertFalse(any(route.upper().endswith("N") for route in filtered_options))
        self.assertFalse(any(
            route.upper().endswith(("H", "T")) and route_app.lines.loc[route, "mode"] == "tram"
            for route in filtered_options
        ))
        self.assertTrue(set(filtered_options).isdisjoint(route_app.LAHIBUSSI_ROUTES))
        self.assertTrue(set(filtered_options).issubset(all_options))

    def test_game_and_solo_store_special_route_settings(self):
        client = route_app.app.test_client()
        created = client.post("/games", data={
            "nickname": "Host",
            "route_count": "3",
            "modes": ["bus", "tram"],
            "zones": ["A", "B"],
        })
        game_id = created.headers["Location"].rstrip("/").split("/")[-1]
        game = route_app.get_game(game_id)
        self.assertFalse(game["include_night_routes"])
        self.assertFalse(game["include_alternative_routes"])
        self.assertFalse(game["include_lahibussi_routes"])
        self.assertEqual(game["zones"], ["A", "B"])
        self.assertTrue(all(
            set(route_app.lines.loc[route, "zones"]).issubset({"A", "B"})
            for route in game["routes"]
        ))
        self.assertFalse(any(route.upper().endswith("N") for route in game["routes"]))
        self.assertFalse(any(
            route.upper().endswith(("H", "T")) and route_app.lines.loc[route, "mode"] == "tram"
            for route in game["routes"]
        ))
        self.assertTrue(set(game["routes"]).isdisjoint(route_app.LAHIBUSSI_ROUTES))

        started = client.post("/solo/start", data={
            "route_count": "3",
            "modes": ["tram"],
            "zones": list(route_app.HSL_ZONES),
            "include_night_routes": "1",
        })
        self.assertEqual(started.status_code, 302)
        with client.session_transaction() as solo_session:
            solo_game = solo_session["solo_game"]
        self.assertTrue(solo_game["include_night_routes"])
        self.assertFalse(solo_game["include_alternative_routes"])
        self.assertFalse(solo_game["include_lahibussi_routes"])

    def test_leaving_multiplayer_notifies_the_other_player(self):
        host = route_app.app.test_client()
        guest = route_app.app.test_client()
        created = host.post("/games", data={
            "nickname": "Host",
            "route_count": "3",
            "modes": ["bus"],
            "zones": list(route_app.HSL_ZONES),
        })
        game_id = created.headers["Location"].rstrip("/").split("/")[-1]
        guest.get(f"/games/{game_id}")
        guest.post(f"/games/{game_id}/join", data={"nickname": "Guest"})

        play_page = guest.get(f"/games/{game_id}/play")
        self.assertIn(b"Keskeyt\xc3\xa4 peli", play_page.data)
        left = guest.post(f"/games/{game_id}/leave")

        self.assertEqual(left.status_code, 302)
        self.assertEqual(left.headers["Location"], "/")
        game = route_app.get_game(game_id)
        self.assertEqual(game["status"], "abandoned")
        self.assertEqual(game["left_by"], "guest")
        self.assertEqual(game["left_name"], "Guest")
        host_state = host.get(f"/games/{game_id}/state").json
        self.assertTrue(host_state["opponent_left"])
        self.assertEqual(host_state["left_name"], "Guest")
        self.assertIn(b"Peli keskeytyi", host.get(f"/games/{game_id}/play").data)

    def test_leaving_solo_clears_the_game(self):
        client = route_app.app.test_client()
        client.post("/solo/start", data={
            "route_count": "3",
            "modes": ["bus"],
            "zones": list(route_app.HSL_ZONES),
        })
        self.assertIn(b"Keskeyt\xc3\xa4 peli", client.get("/solo").data)

        left = client.post("/solo/leave")

        self.assertEqual(left.status_code, 302)
        self.assertEqual(left.headers["Location"], "/")
        with client.session_transaction() as solo_session:
            self.assertNotIn("solo_game", solo_session)

    def test_home_and_solo_map_render(self):
        client = route_app.app.test_client()
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'value="ferry"', home.data)
        for zone in route_app.HSL_ZONES:
            self.assertIn(f'name="zones" value="{zone}"'.encode(), home.data)
        self.assertEqual(client.get("/solo").status_code, 200)
        map_response = client.get("/solo/map")
        self.assertEqual(map_response.status_code, 200)
        self.assertIn(b"leaflet", map_response.data.lower())

    def test_solo_uses_selected_count_and_modes(self):
        client = route_app.app.test_client()
        started = client.post("/solo/start", data={
            "route_count": "3",
            "modes": ["tram"],
            "zones": list(route_app.HSL_ZONES),
            "include_night_routes": "1",
            "include_alternative_routes": "1",
            "include_lahibussi_routes": "1",
        })
        self.assertEqual(started.status_code, 302)
        with client.session_transaction() as solo_session:
            game = solo_session["solo_game"]
        self.assertEqual(len(game["routes"]), 3)
        self.assertEqual(game["modes"], ["tram"])
        self.assertTrue(all(route_app.lines.loc[route, "mode"] == "tram" for route in game["routes"]))

        page = client.get("/solo")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data.count(b'<option value="') - 1, 4)
        bus_route = route_app.route_options(["bus"])[0].encode()
        self.assertNotIn(b'value="' + bus_route + b'"', page.data)


if __name__ == "__main__":
    unittest.main()
