/* Historial compartido para el sitio en Netlify.
   GET  /api/datos?versiones -> {vib: ts, mot: ts, ...}: cuándo se guardó cada técnica (una consulta ligera; la página la revisa
                                cada 30 s y solo descarga la técnica que cambió)
   GET  /api/datos?mod=vib  -> datos guardados de esa técnica ({vacio:true} si todavía no hay)
   PUT  /api/datos?mod=vib  -> guarda los datos (pide la clave de edición en el encabezado x-clave)
   Los datos se guardan en Netlify Blobs (almacén "orios" en el sitio principal, "orios-pruebas" en ramas de prueba; una entrada por técnica).
   La clave se configura en Netlify: Site configuration > Environment variables > ORIOS_CLAVE. */
import { getStore } from "@netlify/blobs";

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

export default async (req, context) => {
  const q = new URL(req.url).searchParams;
  const mod = q.get("mod") || "";
  if (!q.has("versiones") && !/^[a-z]{2,8}$/.test(mod)) return json({ error: "Técnica inválida" }, 400);
  /* el sitio principal usa "orios"; las ramas de prueba y las vistas previas usan otro almacén para no tocar los datos reales */
  const deploy = context?.deploy?.context || "production";
  const store = getStore({ name: deploy === "production" ? "orios" : "orios-pruebas", consistency: "strong" });

  if (req.method === "GET" && q.has("versiones")) return json((await store.get("_versiones", { type: "json" })) || {});

  if (req.method === "GET") {
    const d = await store.get(mod, { type: "json" });
    return json(d || { vacio: true });
  }

  if (req.method === "PUT") {
    const clave = Netlify.env.get("ORIOS_CLAVE");
    if (!clave) return json({ error: "Falta configurar la variable ORIOS_CLAVE en Netlify" }, 503);
    if (req.headers.get("x-clave") !== clave) return json({ error: "Clave de edición incorrecta" }, 401);
    let body;
    try { body = await req.json(); } catch { return json({ error: "Datos inválidos" }, 400); }
    if (!body || !Array.isArray(body.eq) || !Array.isArray(body.cargas)) return json({ error: "Datos inválidos" }, 400);
    /* si alguien guardó mientras tanto, no se pisa su trabajo: se regresan los datos actuales */
    const cur = await store.get(mod, { type: "json" });
    if (cur && cur.ts && body.base !== cur.ts) return json({ error: "conflicto", actual: cur }, 409);
    const doc = { v: 2, eq: body.eq, cargas: body.cargas.slice(0, 300), ts: Date.now() };
    await store.setJSON(mod, doc);
    const ver = (await store.get("_versiones", { type: "json" })) || {};
    ver[mod] = doc.ts;
    await store.setJSON("_versiones", ver);
    return json({ ts: doc.ts });
  }

  return json({ error: "Método no permitido" }, 405);
};

export const config = { path: "/api/datos" };
