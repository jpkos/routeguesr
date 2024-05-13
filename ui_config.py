from folium import Element
#%%
html_banner = '''
<div id="maptitle" style="position: fixed; top: 100px; left: 10px; width: 360px; z-index: 9999; font-size: 12px; border-radius: 5px; color: black; background-color: rgba(255, 255, 255, 0.85); padding: 5px; box-shadow: 0 0 10px rgba(0,0,0,0.3);">
    <h4>Mikä linja tässä kulkee?</h4>
    <p> Kokeile, kuinka hyvin tunnet HSL:n joukkoliikenteen reitit ja linjat! </p>
    <p> Sovelluksen lähdekoodin löydät <a href="https://github.com/jpkos/routeguesr" target="_blank">sen Github-reposta</a>
    <p> Virheilmoitukset ja parannusehdotukset: </p>
    <p> koskinen.jani.p [at) gmail.com </p>
    </div>
<script>
    var title = L.control({position: 'topleft'});
    title.onAdd = function (map) {
        var div = L.DomUtil.get("maptitle");
        return div;
    };
    title.addTo({{this}});
</script>
'''
title_html = Element(html_banner)
#%%
ZOOM_LVL = 12
LINE_COLOR = '#007AC9'