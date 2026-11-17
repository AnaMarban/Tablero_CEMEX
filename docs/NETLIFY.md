# Sitio en Netlify con historial compartido

En Netlify el tablero guarda las actualizaciones en un solo lugar (Netlify Blobs), así que **lo que alguien carga lo ven todos** los que abren la página. Abierto como archivo (doble clic en `dist/Cemex_Orios.html`) sigue funcionando como antes, solo en esa computadora.

## Cómo funciona

- `netlify/functions/datos.mjs` es un servicio pequeño en `/api/datos`:
  - `GET /api/datos?mod=vib` regresa los datos guardados de esa técnica.
  - `PUT /api/datos?mod=vib` guarda, y pide la clave de edición.
  - `GET /api/datos?versiones` dice cuándo se guardó por última vez cada técnica.
- Al abrir la página se leen los datos compartidos. **Las sesiones abiertas se actualizan solas**: cada 30 segundos, y al regresar a la pestaña, la página hace una consulta ligera (`?versiones`). Si alguien guardó algo, descarga solo esa técnica, redibuja la pantalla sin recargar y avisa "Datos actualizados por otra persona".
- Consumo: una consulta cada 30 s por sesión abierta, más una descarga cuando alguien guarda. Cabe con holgura en el nivel gratuito de Netlify para un grupo pequeño.
- Mientras nadie guarde nada, cada técnica muestra el historial que trae la página (la semilla). La primera vez que alguien guarda, ese historial más su archivo se vuelve el historial compartido.
- **Clave de edición.** Ver los datos no pide clave; guardar sí. La página la pide la primera vez y la recuerda en ese navegador. Si alguien la escribe mal, su carga queda solo en su computadora.
- **Dos personas guardando a la vez.** Si alguien guardó mientras otra persona revisaba su archivo, a esa persona se le recalcula su carga contra lo más reciente y solo tiene que presionar Guardar otra vez. No se pierde nada.
- **"Ver formato original".** El archivo original de una carga queda solo en la computadora de quien lo cargó. Los demás ven el historial, pero no el archivo.

## Configuración en Netlify (una sola vez)

1. **Site configuration → Environment variables → Add a variable**: nombre `ORIOS_CLAVE`, valor = la clave que quieras usar para guardar. Compártela solo con quien deba actualizar.
2. **Deploys → Trigger deploy → Deploy site**, para que el servicio tome la clave.
3. Abre el sitio. Junto a la fecha debe aparecer **● datos compartidos**.

No hace falta crear una base de datos: Netlify Blobs viene incluido en el sitio. `package.json` solo instala `@netlify/blobs` para el servicio, y `netlify.toml` fija Node 22.

## Cambios visuales o de código

Netlify arma la página en cada subida (`python3 scripts/build.py`, definido en `netlify.toml`). Basta con editar `src/template.html` y subirlo a GitHub. En uno o dos minutos el sitio queda actualizado, y los datos compartidos no se pierden.

No edites `dist/` a mano: se vuelve a generar en cada subida.

## Seguir desarrollando sin afectar a quien ya lo usa

- Trabaja en una rama `desarrollo`. En Netlify, en **Site configuration → Build & deploy → Branches and deploy contexts → Branch deploys**, agrega esa rama. Tendrá su propia liga.
- La versión de pruebas guarda en otro almacén (`orios-pruebas`; lo decide `netlify/functions/datos.mjs` según el tipo de despliegue), así que lo que cargues ahí no altera el historial real. Cuando el cambio esté listo, se pasa `desarrollo` → `main`.
- Los datos guardados no se borran al publicar una versión nueva de la página.

## Cuidado

El sitio es público: quien tenga la liga ve los datos de planta. La clave solo protege que nadie los cambie. Confirma con TI que se puede publicar.
