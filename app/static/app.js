/* Pizarra digital de interinatos y licencias — interfaz (JavaScript sin dependencias,
   para que funcione en un servidor sin acceso a internet). */
"use strict";

// ── Utilidades ────────────────────────────────────────────────────────
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const DIAS = ["Do", "Lu", "Ma", "Mi", "Ju", "Vi", "Sá"];
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

const aFecha = (iso) => new Date(iso + "T00:00:00Z");
const aIso = (d) => d.toISOString().slice(0, 10);
const sumar = (iso, n) => { const d = aFecha(iso); d.setUTCDate(d.getUTCDate() + n); return aIso(d); };
const difDias = (a, b) => Math.round((aFecha(b) - aFecha(a)) / 86400000);
const fmt = (iso) => (iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(0, 4) : "");
const fmtCorto = (iso) => iso.slice(8, 10) + "/" + iso.slice(5, 7);
const fmtHora = (ts) => (ts ? new Date(ts).toLocaleString("es-PY", { dateStyle: "short", timeStyle: "short" }) : "");
const lunesDe = (iso) => { const d = aFecha(iso); const w = (d.getUTCDay() + 6) % 7; return sumar(iso, -w); };
const finDeSemana = (iso) => [0, 6].includes(aFecha(iso).getUTCDay());

/** Nombre del despacho, con el turno si no figura ya en el nombre. */
const conTurno = (despacho, turno) =>
  turno && !String(despacho).toLowerCase().includes(String(turno).toLowerCase()) ? `${despacho} · ${turno}` : despacho;

const SRIAS = Array.from({ length: 10 }, (_, i) => `Nº ${i + 1}`);   // sugeridas; se puede escribir otra
const minusInicial = (t) => (t ? t[0].toLowerCase() + t.slice(1) : t);

const pref = {
  leer(k, def) { try { const v = localStorage.getItem("pizarra." + k); return v === null ? def : JSON.parse(v); } catch { return def; } },
  guardar(k, v) { try { localStorage.setItem("pizarra." + k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } },
};

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

class ErrorApi extends Error {
  constructor(status, data) { super(data?.detail || "Error " + status); this.status = status; this.data = data; }
}

async function api(metodo, url, cuerpo) {
  const op = { method: metodo, headers: {} };
  if (cuerpo instanceof FormData) op.body = cuerpo;
  else if (cuerpo !== undefined) { op.headers["Content-Type"] = "application/json"; op.body = JSON.stringify(cuerpo); }
  const r = await fetch(url, op);
  if (r.status === 401) { location.href = "/login"; throw new ErrorApi(401, {}); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ErrorApi(r.status, data);
  return data;
}

function detalleError(d) {
  if (!d) return "Error desconocido";
  if (typeof d.detail === "string") return d.detail;
  if (Array.isArray(d.detail)) return d.detail.map((x) => `${(x.loc || []).slice(-1)[0]}: ${x.msg}`).join(" · ");
  return "Error";
}

const listaHallazgos = (hs) =>
  `<ul class="hallazgos">${hs.map((h) => `<li class="h-${esc(h.nivel)}">${esc(h.mensaje)}</li>`).join("")}</ul>`;

function mostrarError(e) {
  if (e?.data?.hallazgos) {
    const titulo = e.data.tipo === "VERSION" ? "⚠ El registro cambió" : "⛔ No se puede guardar";
    modal($("#modal2"), { titulo, cuerpo: listaHallazgos(e.data.hallazgos) +
      (e.data.tipo === "VERSION" ? "" : `<p class="ayuda">Elija otro funcionario o ajuste las fechas.</p>`),
      pie: [{ texto: "Entendido", clase: "primario" }] });
  } else if (e instanceof ErrorApi) {
    toast(detalleError(e.data), 6000);
  } else {
    console.error(e);
    toast("No hay conexión con el servidor.", 6000);
  }
}

/** Abre un diálogo. pie: [{texto, clase, accion(cerrar) -> (false para no cerrar)}] */
function modal(dlg, { titulo, cuerpo, pie = [], ancho = false, alCerrar }) {
  dlg.className = ancho ? "ancho" : "";
  dlg.innerHTML = `<div class="modal-cab"><h2>${esc(titulo)}</h2><button class="cerrar" aria-label="Cerrar">×</button></div>
    <div class="modal-cuerpo"></div><div class="modal-pie"></div>`;
  const c = $(".modal-cuerpo", dlg);
  if (typeof cuerpo === "string") c.innerHTML = cuerpo; else if (cuerpo) c.append(cuerpo);
  const cerrar = () => { if (dlg.open) dlg.close(); };
  dlg.onclose = () => alCerrar && alCerrar();
  $(".cerrar", dlg).onclick = cerrar;
  const piePanel = $(".modal-pie", dlg);
  if (!pie.length) piePanel.remove();
  for (const b of pie) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "btn " + (b.clase || "");
    el.textContent = b.texto;
    if (b.id) el.id = b.id;
    el.onclick = async () => {
      if (!b.accion) return cerrar();
      el.disabled = true;
      try { if ((await b.accion(cerrar)) !== false) cerrar(); }
      finally { el.disabled = false; }
    };
    piePanel.append(el);
  }
  if (!dlg.open) dlg.showModal();
  return { dlg, cuerpo: c, cerrar };
}

function confirmar(titulo, html, textoOk = "Confirmar") {
  return new Promise((ok) => {
    let r = false;
    modal($("#modal2"), {
      titulo, cuerpo: html,
      pie: [{ texto: "Cancelar" }, { texto: textoOk, clase: "primario", accion: () => { r = true; } }],
      alCerrar: () => ok(r),
    });
  });
}

// ── Estado ────────────────────────────────────────────────────────────
const E = {
  yo: null, hoy: null, cat: null, datos: null, alertas: null,
  desde: null, largo: pref.leer("largo", 14), vista: pref.leer("vista", "cargo"),
  colapsados: new Set(pref.leer("colapsados", [])),
};
const personaPorId = () => new Map(E.datos.personal.map((p) => [p.id, p]));

// ── Carga de datos ────────────────────────────────────────────────────
async function iniciar() {
  try {
    E.yo = await api("GET", "/api/yo");
  } catch { return; }
  E.hoy = E.yo.hoy;
  E.desde = lunesDe(E.hoy);
  $("#nombre-usuario").textContent = E.yo.nombre;
  $("#m-version").textContent = `Versión ${E.yo.version}`;
  $("#circunscripcion").textContent = "· " + E.yo.circunscripcion;
  $("#m-admin").hidden = E.yo.rol !== "ADMIN";
  $("#largo").value = String(E.largo);
  $("#vista").value = E.vista;
  E.cat = await api("GET", "/api/catalogos");
  $("#f-cargo").insertAdjacentHTML("beforeend", E.cat.cargos.map((c) => `<option value="${c.codigo}">${esc(c.nombre)}</option>`).join(""));
  const fueros = [...new Set(E.cat.despachos.map((d) => d.fuero))].sort();
  const locs = [...new Set(E.cat.despachos.map((d) => d.localidad))].sort();
  $("#f-fuero").insertAdjacentHTML("beforeend", fueros.map((f) => `<option>${esc(f)}</option>`).join(""));
  $("#f-localidad").insertAdjacentHTML("beforeend", locs.map((f) => `<option>${esc(f)}</option>`).join(""));
  const turnos = [...new Set(E.cat.despachos.map((d) => d.turno).filter(Boolean))].sort();
  $("#l-turno").hidden = !turnos.length;
  $("#f-turno").insertAdjacentHTML("beforeend", turnos.map((t) => `<option>${esc(t)}</option>`).join(""));
  $("#f-novedades").checked = pref.leer("novedades", true);
  conectarEventos();
  await recargar();
}

async function recargar() {
  const hasta = sumar(E.desde, E.largo - 1);
  $("#rango").textContent = `${fmtCorto(E.desde)} – ${fmt(hasta)}`;
  try {
    const [datos, alertas] = await Promise.all([
      api("GET", `/api/pizarra?desde=${E.desde}&hasta=${hasta}`),
      api("GET", "/api/alertas"),
    ]);
    E.datos = datos;
    E.alertas = alertas;
    E.hoy = datos.hoy;
    dibujarAlertas();
    dibujarPizarra();
  } catch (e) { mostrarError(e); }
}

// ── Alertas ───────────────────────────────────────────────────────────
function dibujarAlertas() {
  const a = E.alertas, el = $("#alertas");
  const vac = a.vacantes_sin_cubrir || [];
  const n = a.sin_cubrir.length + a.en_conflicto.length + vac.length;
  el.hidden = n === 0;
  if (!n) return;
  const abierto = pref.leer("alertasAbiertas", innerWidth > 700);
  el.innerHTML = `<details ${abierto ? "open" : ""}><summary>⚠ ${n} alerta(s): ${a.sin_cubrir.length} ausente(s) sin cubrir${vac.length ? ` · ${vac.length} puesto(s) vacante(s) sin nadie a cargo` : ""} · ${a.en_conflicto.length} interinato(s) en conflicto</summary><ul>
    ${a.sin_cubrir.map((x, i) => `<li><b>${esc(x.nombre_completo)}</b> (${esc(x.cargo)}, ${esc(x.despacho)}) — licencia ${esc(x.tipo).toLowerCase()} del ${fmt(x.fecha_inicio)} al ${fmt(x.fecha_fin)}: <b>${x.dias_sin_cubrir} día(s) hábil(es) sin interino</b> desde el ${fmt(x.primer_dia)}.
      <button class="btn chico" data-asignar="${i}">Asignar interino</button></li>`).join("")}
    ${vac.map((x, i) => `<li>⚪ <b>Puesto vacante de ${esc(x.cargo)}${x.secretaria ? " (Sria. " + esc(x.secretaria) + ")" : ""}</b> en ${esc(x.despacho)}: <b>${x.dias_sin_cubrir} día(s) hábil(es) sin nadie a cargo</b> desde el ${fmt(x.primer_dia)}.
      <button class="btn chico" data-vacante="${i}">Asignar a cargo</button></li>`).join("")}
    ${a.en_conflicto.map((x) => `<li>⚡ Interinato de <b>${esc(x.interino)}</b> cubriendo a ${esc(x.titular)} (${fmt(x.fecha_inicio)}–${fmt(x.fecha_fin)}) está <b>EN CONFLICTO</b>: el interino tiene licencia.
      <button class="btn chico" data-conflicto="${x.id}">Resolver</button></li>`).join("")}
  </ul></details>`;
  $("details", el).ontoggle = (ev) => pref.guardar("alertasAbiertas", ev.target.open);
  $$("[data-asignar]", el).forEach((b) => (b.onclick = () => {
    const x = a.sin_cubrir[+b.dataset.asignar];
    formInterinato({ titular_id: x.personal_id, fecha_inicio: x.primer_dia, fecha_fin: x.fecha_fin, licencia_id: x.licencia_id });
  }));
  $$("[data-conflicto]", el).forEach((b) => (b.onclick = () => verInterinato(+b.dataset.conflicto)));
  $$("[data-vacante]", el).forEach((b) => (b.onclick = () => {
    const x = vac[+b.dataset.vacante];
    formInterinato({ vacante_id: x.vacante_id, fecha_inicio: x.primer_dia, fecha_fin: x.fecha_hasta || x.ultimo_dia });
  }));
}

// ── Pizarra ───────────────────────────────────────────────────────────
function diasVisibles() {
  const inh = new Map(E.datos.inhabiles.map((x) => [x.fecha, x.descripcion]));
  return Array.from({ length: E.largo }, (_, i) => {
    const f = sumar(E.desde, i);
    return { f, i, inhabil: finDeSemana(f) || inh.has(f), motivo: inh.get(f) || "", hoy: f === E.hoy };
  });
}

/** Calcula las barras de cada persona y en qué carril (fila interna) van. */
function eventosDe(p, dias) {
  const { licencias, interinatos } = E.datos;
  const ini = E.desde, fin = sumar(E.desde, E.largo - 1);
  const col = (iso) => Math.max(0, difDias(ini, iso));
  const recorte = (a, b) => [a < ini ? ini : a, b > fin ? fin : b];
  const carriles = [];
  const esVac = !!p.esVacante, vac = p.vac;
  // Para un puesto vacante, el "período de ausencia" es el de la vacancia
  const lic = esVac ? [{ id: vac.id, fecha_inicio: vac.fecha_desde, fecha_fin: vac.fecha_hasta || "9999-12-31" }]
                    : licencias.filter((l) => l.personal_id === p.id);
  const comoTitular = esVac ? interinatos.filter((i) => i.vacante_id === vac.id)
                            : interinatos.filter((i) => i.titular_id === p.id);
  const comoInterino = esVac ? [] : interinatos.filter((i) => i.interino_id === p.id).sort((a, b) => (a.fecha_inicio < b.fecha_inicio ? -1 : 1));

  if (esVac) {
    const [a, b] = recorte(vac.fecha_desde, vac.fecha_hasta || "9999-12-31");
    carriles.push([{ tipo: "vacante", c0: col(a), c1: col(b), texto: `PUESTO VACANTE${vac.secretaria ? " · Sria. " + vac.secretaria : ""}`,
                     titulo: `Vacante desde el ${fmt(vac.fecha_desde)}${vac.fecha_hasta ? " hasta el " + fmt(vac.fecha_hasta) : ""}`, ref: vac }]);
  } else if (lic.length) {
    carriles.push(lic.map((l) => {
      const [a, b] = recorte(l.fecha_inicio, l.fecha_fin);
      return { tipo: "licencia", c0: col(a), c1: col(b), texto: `${l.tipo.toUpperCase()}${l.tiene_adjunto ? " 📎" : ""}`,
               titulo: `Licencia ${l.tipo}: ${fmt(l.fecha_inicio)} al ${fmt(l.fecha_fin)}`, ref: l };
    }));
  }
  // Carril de cobertura: quién cubre cada día de ausencia (o ⚠ si nadie)
  if (lic.length || comoTitular.length) {
    const segs = [];
    let actual = null;
    for (const d of dias) {
      const enLic = lic.find((l) => l.fecha_inicio <= d.f && d.f <= l.fecha_fin);
      const cub = comoTitular.find((i) => i.fecha_inicio <= d.f && d.f <= i.fecha_fin);
      let clave = null;
      if (cub) clave = "c" + cub.id;
      else if (enLic && !d.inhabil) clave = "s" + enLic.id;
      if (actual && actual.clave === clave && clave) { actual.c1 = d.i; continue; }
      actual = clave ? { clave, c0: d.i, c1: d.i, cub, enLic } : null;
      if (actual) segs.push(actual);
    }
    if (segs.length) {
      carriles.push(segs.map((s) => s.cub
        ? { tipo: s.cub.estado === "EN_CONFLICTO" ? "conflicto" : "cubierto", c0: s.c0, c1: s.c1,
            texto: `${s.cub.estado === "EN_CONFLICTO" ? "⚡" : "✔"} ${esVac ? "a cargo" : "cubre"}: ${s.cub.interino}`,
            titulo: `Interino: ${s.cub.interino} (${fmt(s.cub.fecha_inicio)} al ${fmt(s.cub.fecha_fin)})`, ref: s.cub }
        : { tipo: "sin-cubrir", c0: s.c0, c1: s.c1, texto: esVac ? "⚠ SIN NADIE A CARGO" : "⚠ SIN CUBRIR",
            titulo: "Clic para asignar un interino",
            ref: esVac ? { vacante_id: vac.id, fecha_inicio: sumar(E.desde, s.c0), fecha_fin: sumar(E.desde, s.c1) }
                       : { titular_id: p.id, fecha_inicio: sumar(E.desde, s.c0), fecha_fin: sumar(E.desde, s.c1), licencia_id: s.enLic.id } }));
    }
  }
  // Interinatos que la persona cubre (los jueces pueden tener varios a la vez)
  const pilas = [];
  for (const it of comoInterino) {
    const [a, b] = recorte(it.fecha_inicio, it.fecha_fin);
    const ev = { tipo: it.estado === "EN_CONFLICTO" ? "conflicto" : "interino", c0: col(a), c1: col(b),
                 texto: `${it.estado === "EN_CONFLICTO" ? "⚡ " : ""}${it.vacante_id ? "A CARGO de " + minusInicial(it.titular) : "INTERINO de " + it.titular} · ${it.despacho_titular}`,
                 titulo: `${it.vacante_id ? "A cargo de " + minusInicial(it.titular) : "Interino de " + it.titular} (${it.despacho_titular}) del ${fmt(it.fecha_inicio)} al ${fmt(it.fecha_fin)}`, ref: it };
    let k = pilas.findIndex((pl) => pl.every((o) => o.c1 < ev.c0 || o.c0 > ev.c1));
    if (k < 0) { pilas.push([]); k = pilas.length - 1; }
    pilas[k].push(ev);
  }
  carriles.push(...pilas);
  // Máximo de despachos cubiertos en un mismo día
  let carga = 0;
  for (const d of dias) carga = Math.max(carga, comoInterino.filter((i) => i.fecha_inicio <= d.f && d.f <= i.fecha_fin).length);
  return { carriles, carga };
}

function filtrar(p) {
  const fc = $("#f-cargo").value, ff = $("#f-fuero").value, fl = $("#f-localidad").value, ft = $("#f-turno").value;
  const q = $("#f-buscar").value.trim().toLowerCase();
  if (fc && p.cargo_codigo !== fc) return false;
  if (ff && p.fuero !== ff) return false;
  if (ft && p.turno !== ft) return false;
  if (fl && p.localidad !== fl) return false;
  if (q && !(p.nombre_completo + " " + p.despacho).toLowerCase().includes(q)) return false;
  return true;
}

/** Un puesto vacante se muestra como una fila más de la pizarra. */
const filaVacante = (v) => ({
  id: "v" + v.id, esVacante: true, vac: v, nombre_completo: "Puesto vacante", cargo: v.cargo,
  cargo_codigo: v.cargo_codigo, orden_pizarra: v.orden_pizarra, despacho: v.despacho, despacho_id: v.despacho_id,
  fuero: v.fuero, localidad: v.localidad, turno: v.turno, secretaria: v.secretaria,
});

/** "Juez: Cáceres, Silvia (a cargo hoy: X, interino)" para el encabezado de cada despacho. */
function juezResponsable(despachoId) {
  const fin = sumar(E.desde, E.largo - 1);
  const ref = E.hoy >= E.desde && E.hoy <= fin ? E.hoy : E.desde;
  const etq = ref === E.hoy ? "hoy" : `el ${fmtCorto(ref)}`;
  const vigente = (x, a = "fecha_inicio", b = "fecha_fin") => x[a] <= ref && (!x[b] || ref <= x[b]);
  const partes = [];
  for (const j of E.datos.personal.filter((p) => p.despacho_id === despachoId && p.cargo_codigo === "JUEZ")) {
    const cub = E.datos.interinatos.find((i) => i.titular_id === j.id && vigente(i));
    const lic = E.datos.licencias.find((l) => l.personal_id === j.id && vigente(l));
    partes.push(`Juez: ${j.nombre_completo}` + (cub ? ` (a cargo ${etq}: ${cub.interino}, interino)` : lic ? ` (⚠ de licencia ${etq}, sin interino)` : ""));
  }
  for (const v of E.datos.vacantes.filter((v) => v.despacho_id === despachoId && v.cargo_codigo === "JUEZ" && vigente(v, "fecha_desde", "fecha_hasta"))) {
    const cub = E.datos.interinatos.find((i) => i.vacante_id === v.id && vigente(i));
    partes.push(`Juez: cargo vacante` + (cub ? ` (a cargo ${etq}: ${cub.interino})` : ` (⚠ sin nadie a cargo ${etq})`));
  }
  return partes.join(" · ");
}

function dibujarPizarra() {
  const dias = diasVisibles();
  const tab = $("#tablero");
  const soloNov = $("#f-novedades").checked;
  const porCargo = E.vista === "cargo";
  const grupos = new Map();
  for (const p of [...E.datos.personal, ...E.datos.vacantes.map(filaVacante)]) {
    if (!filtrar(p)) continue;
    const ev = eventosDe(p, dias);
    const clave = porCargo ? p.cargo_codigo : "d" + p.despacho_id;
    if (!grupos.has(clave)) {
      grupos.set(clave, { titulo: porCargo ? p.cargo : p.despacho, sub: porCargo ? "" : [p.fuero, p.turno && !p.despacho.includes(p.turno) ? p.turno : "", p.localidad].filter(Boolean).join(" · "),
                          orden: porCargo ? p.orden_pizarra : p.localidad + p.despacho, filas: [], total: 0,
                          juez: porCargo ? "" : juezResponsable(p.despacho_id) });
    }
    const g = grupos.get(clave);
    g.total++;
    if (ev.carriles.length || !soloNov) g.filas.push({ p, ev });
  }
  const lista = [...grupos.entries()].sort((a, b) => (a[1].orden < b[1].orden ? -1 : 1));
  if (!porCargo) lista.forEach(([, g]) => g.filas.sort((a, b) => a.p.orden_pizarra - b.p.orden_pizarra
    || String(a.p.secretaria || "~").localeCompare(String(b.p.secretaria || "~")) || !!a.p.esVacante - !!b.p.esVacante));

  const estiloDias = `style="--dias:${dias.length}"`;
  let html = `<div class="grilla"><div class="fila cabecera" ${estiloDias}><div class="esquina">${porCargo ? "Cargo / Funcionario" : "Despacho / Funcionario"}</div>`;
  for (const d of dias) {
    const dt = aFecha(d.f);
    const mes = d.i === 0 || dt.getUTCDate() === 1 ? `<span class="mes">${MESES[dt.getUTCMonth()]}</span>` : "";
    html += `<div class="dia ${d.inhabil ? "inhabil" : ""} ${d.hoy ? "hoy" : ""}" title="${esc(d.motivo || fmt(d.f))}">${mes}${DIAS[dt.getUTCDay()]}<b>${dt.getUTCDate()}</b></div>`;
  }
  html += `</div>`;
  let filas = 0;
  for (const [clave, g] of lista) {
    if (soloNov && !g.filas.length && lista.length > 1) {
      html += `<div class="grupo" data-grupo="${esc(clave)}">▶ ${esc(g.titulo)} <span class="cuenta">${esc(g.sub)} · sin novedades (${g.total})</span>${g.juez ? `<span class="juez">${esc(g.juez)}</span>` : ""}</div>`;
      continue;
    }
    const col = E.colapsados.has(clave);
    html += `<div class="grupo" data-grupo="${esc(clave)}">${col ? "▶" : "▼"} ${esc(g.titulo)} <span class="cuenta">${esc(g.sub)}${g.sub ? " · " : ""}${g.filas.length} ${soloNov ? "con novedades" : "funcionarios"} / ${g.total}</span>${g.juez ? `<span class="juez">${esc(g.juez)}</span>` : ""}</div>`;
    if (col) continue;
    for (const { p, ev } of g.filas) {
      filas++;
      const n = Math.max(1, ev.carriles.length);
      const sria = p.secretaria ? ` · Sria. ${p.secretaria}` : "";
      const sub = (porCargo ? conTurno(p.despacho, p.turno) : p.cargo) + sria;
      html += `<div class="fila${p.esVacante ? " vacante" : ""}" ${estiloDias} data-pid="${p.id}">
        <div class="nombre" style="grid-row:1 / span ${n}"><span class="n">${p.esVacante ? "⚪ " : ""}${esc(p.nombre_completo)}${ev.carga >= 2 ? `<span class="carga" title="Despachos que cubre a la vez">cubre ${ev.carga}</span>` : ""}</span><span class="s" title="${esc(sub)}">${esc(sub)}</span></div>`;
      for (const d of dias) {
        html += `<div class="celda ${d.inhabil ? "inhabil" : ""} ${d.hoy ? "hoy" : ""}" style="grid-column:${d.i + 2};grid-row:1 / span ${n}" data-i="${d.i}"></div>`;
      }
      ev.carriles.forEach((carril, k) => carril.forEach((b, j) => {
        html += `<div class="barra-evento ev-${b.tipo}" style="grid-column:${b.c0 + 2} / ${b.c1 + 3};grid-row:${k + 1}" title="${esc(b.titulo)}" data-k="${k}" data-j="${j}">${esc(b.texto)}</div>`;
      }));
      html += `</div>`;
    }
  }
  html += `</div>`;
  if (!filas && !lista.length) html = `<div class="vacio">No hay funcionarios que coincidan con los filtros.</div>`;
  else if (!filas && soloNov) html += `<div class="vacio">Sin licencias ni interinatos en este período. Desmarque «Solo con novedades» para ver a todo el personal.</div>`;
  tab.innerHTML = html;
  ajustarAncho();

  // Guardar los eventos por fila para resolver los clics
  const mapa = new Map();
  for (const [, g] of lista) for (const f of g.filas) mapa.set(String(f.p.id), f.ev);
  $$(".barra-evento", tab).forEach((el) => {
    const pid = el.closest(".fila").dataset.pid;
    const b = mapa.get(pid).carriles[+el.dataset.k][+el.dataset.j];
    el.onclick = () => {
      if (b.tipo === "licencia") verLicencia(b.ref.id);
      else if (b.tipo === "vacante") verVacante(b.ref.id);
      else if (b.tipo === "sin-cubrir") formInterinato(b.ref);
      else verInterinato(b.ref.id);
    };
  });
  $$(".grupo", tab).forEach((el) => (el.onclick = () => {
    const c = el.dataset.grupo;
    if (E.colapsados.has(c)) E.colapsados.delete(c); else E.colapsados.add(c);
    pref.guardar("colapsados", [...E.colapsados]);
    dibujarPizarra();
  }));
  activarSeleccion(tab);
}

/** Columnas de día de ancho fijo (iguales en todas las filas), llenando la pantalla. */
function ajustarAncho() {
  const tab = $("#tablero"), g = $(".grilla", tab);
  if (!g) return;
  const css = getComputedStyle(document.documentElement);
  const nombre = parseFloat(css.getPropertyValue("--col-nombre")), minimo = parseFloat(css.getPropertyValue("--col-dia"));
  const ancho = Math.max(minimo, Math.floor((tab.clientWidth - nombre) / E.largo));
  g.style.setProperty("--ancho-dia", ancho + "px");
}
window.addEventListener("resize", () => ajustarAncho());

/** Clic o arrastre sobre los días de una fila -> nueva licencia con esas fechas. */
function activarSeleccion(tab) {
  let sel = null;
  const pintar = () => $$(".celda", sel.fila).forEach((c) => {
    const i = +c.dataset.i;
    c.classList.toggle("sel", i >= Math.min(sel.a, sel.b) && i <= Math.max(sel.a, sel.b));
  });
  tab.onpointerdown = (ev) => {
    const c = ev.target.closest(".celda");
    if (!c || ev.button !== 0 || c.closest(".fila").dataset.pid.startsWith("v")) return;   // no en filas de vacantes
    ev.preventDefault();
    sel = { fila: c.closest(".fila"), a: +c.dataset.i, b: +c.dataset.i };
    pintar();
  };
  tab.onpointerover = (ev) => {
    if (!sel) return;
    const c = ev.target.closest(".celda");
    if (c && c.closest(".fila") === sel.fila) { sel.b = +c.dataset.i; pintar(); }
  };
  document.onpointerup = () => {
    if (!sel) return;
    const s = sel; sel = null;
    $$(".celda.sel", s.fila).forEach((c) => c.classList.remove("sel"));
    formLicencia({ personal_id: +s.fila.dataset.pid, fecha_inicio: sumar(E.desde, Math.min(s.a, s.b)),
                   fecha_fin: sumar(E.desde, Math.max(s.a, s.b)) });
  };
}

// ── Licencias ─────────────────────────────────────────────────────────
function opcionesPersonal(seleccion, filtro = () => true) {
  const porCargo = new Map();
  for (const p of E.datos.personal.filter(filtro)) {
    if (!porCargo.has(p.cargo)) porCargo.set(p.cargo, []);
    porCargo.get(p.cargo).push(p);
  }
  return `<option value="">— Seleccione —</option>` + [...porCargo.entries()].map(([c, ps]) =>
    `<optgroup label="${esc(c)}">${ps.map((p) => `<option value="${p.id}" ${p.id === seleccion ? "selected" : ""}>${esc(p.nombre_completo)} — ${esc(conTurno(p.despacho, p.turno))}</option>`).join("")}</optgroup>`).join("");
}

function contarDias(a, b) {
  if (!a || !b || b < a) return "";
  const inh = new Set(E.datos.inhabiles.map((x) => x.fecha));
  let hab = 0;
  const n = difDias(a, b) + 1;
  for (let i = 0; i < n; i++) { const f = sumar(a, i); if (!finDeSemana(f) && !inh.has(f)) hab++; }
  return `→ ${n} día(s) corrido(s) / ${hab} hábil(es)`;
}

/** Lee remitente, asunto y fecha de un correo .eml para completar el formulario. */
function leerEml(texto) {
  const cab = texto.split(/\r?\n\r?\n/)[0].replace(/\r?\n[ \t]+/g, " ");
  const campo = (n) => { const m = cab.match(new RegExp("^" + n + ":\\s*(.*)$", "im")); return m ? decodificarMime(m[1].trim()) : ""; };
  const fecha = campo("Date") ? new Date(campo("Date")) : null;
  return { remitente: campo("From"), asunto: campo("Subject"), fecha: fecha && !isNaN(fecha) ? fecha : null };
}
function decodificarMime(s) {
  return s.replace(/=\?([^?]+)\?([BbQq])\?([^?]*)\?=/g, (_, cs, enc, txt) => {
    try {
      let bytes;
      if (enc.toUpperCase() === "B") bytes = Uint8Array.from(atob(txt), (c) => c.charCodeAt(0));
      else bytes = Uint8Array.from(txt.replace(/_/g, " ").replace(/=([0-9A-F]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16))), (c) => c.charCodeAt(0));
      return new TextDecoder(cs).decode(bytes);
    } catch { return txt; }
  }).replace(/\?=\s+=\?/g, "");
}
const aLocal = (d) => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 16); };

function formLicencia(ini = {}, existente = null) {
  const l = existente || ini;
  const pm = personaPorId();
  let archivo = null;
  let organoManual = !!existente;
  const html = `<form class="form" id="f-lic" autocomplete="off">
    <label class="req" for="l-per">Funcionario</label>
    <select id="l-per" required>${opcionesPersonal(l.personal_id)}</select>
    <label class="req" for="l-tipo">Tipo de licencia</label>
    <div class="fila-campos"><select id="l-tipo" required>${E.cat.tipos_licencia.map((t) => `<option value="${t.id}" ${t.id === l.tipo_licencia_id ? "selected" : ""}>${esc(t.nombre)}</option>`).join("")}</select>
      <span class="ayuda">Aprobada por:</span>
      <label><input type="radio" name="org" value="RRHH"> RRHH</label>
      <label><input type="radio" name="org" value="CONSEJO"> Consejo</label></div>
    <label class="req">Fechas</label>
    <div class="fila-campos">Desde <input type="date" id="l-ini" required value="${esc(l.fecha_inicio || "")}">
      Hasta <input type="date" id="l-fin" required value="${esc(l.fecha_fin || "")}"> <span class="ayuda" id="l-dias"></span></div>
    <label for="l-res">Nº de resolución</label><input type="text" id="l-res" value="${esc(l.nro_resolucion || "")}">
    <h3>Correo de origen</h3>
    <label>Respaldo</label>
    <div><div class="zona-archivo" id="l-zona" tabindex="0">📎 Arrastre aquí el PDF o el correo (.eml), o haga clic para elegirlo
      <input type="file" id="l-archivo" hidden accept=".pdf,.eml,.msg,.png,.jpg,.jpeg,.txt,.doc,.docx"></div>
      <div class="ayuda" id="l-archivo-nombre">${existente?.adjunto_nombre ? "Adjunto actual: " + esc(existente.adjunto_nombre) + " (si elige otro, lo reemplaza)" : "Si arrastra un .eml, se completan remitente, fecha y asunto."}</div></div>
    <label for="l-rem">Remitente</label><input type="text" id="l-rem" value="${esc(l.correo_remitente || "")}">
    <label for="l-fcor">Fecha del correo</label><input type="datetime-local" id="l-fcor" value="${l.correo_fecha ? aLocal(new Date(l.correo_fecha)) : ""}">
    <label for="l-asu">Asunto</label><input type="text" id="l-asu" value="${esc(l.correo_asunto || "")}">
    <label for="l-enl">Enlace externo</label><input type="url" id="l-enl" placeholder="https://… (opcional)" value="${esc(l.enlace_externo || "")}">
    <label for="l-obs">Observaciones</label><textarea id="l-obs">${esc(l.observaciones || "")}</textarea>
    <div class="full" id="l-impacto"></div>
  </form>`;
  const pie = [{ texto: "Cancelar" }, { texto: "Guardar", clase: "primario", accion: () => guardar(false) }];
  if (!existente) pie.push({ texto: "Guardar y asignar interino ▸", clase: "primario", accion: () => guardar(true) });
  const { cuerpo } = modal($("#modal"), { titulo: existente ? `Editar licencia #${existente.id}` : "Nueva licencia", cuerpo: html, pie });
  const f = $("#f-lic", cuerpo);

  const ponerOrgano = () => {
    if (organoManual && existente) { $$(`[name=org]`, f).forEach((r) => (r.checked = r.value === (existente.organo_aprobador))); organoManual = false; return; }
    const p = pm.get(+$("#l-per", f).value);
    const cargo = p && E.cat.cargos.find((c) => c.codigo === p.cargo_codigo);
    if (cargo) $$(`[name=org]`, f).forEach((r) => (r.checked = r.value === cargo.organo_aprobador));
  };
  const impacto = () => {
    const pid = +$("#l-per", f).value, a = $("#l-ini", f).value, b = $("#l-fin", f).value;
    $("#l-dias", f).textContent = contarDias(a, b);
    const el = $("#l-impacto", f);
    if (!pid || !a || !b || b < a) { el.innerHTML = ""; return; }
    const cubre = E.datos.interinatos.filter((i) => i.titular_id === pid && i.fecha_inicio <= b && i.fecha_fin >= a);
    const esInterino = E.datos.interinatos.filter((i) => i.interino_id === pid && i.fecha_inicio <= b && i.fecha_fin >= a);
    const hs = [];
    if (!cubre.length) hs.push({ nivel: "ADVERTENCIA", mensaje: "No tiene interino asignado para estas fechas (según el período visible en la pizarra)." });
    else hs.push({ nivel: "INFO", mensaje: "Cubierto por: " + cubre.map((i) => `${i.interino} (${fmtCorto(i.fecha_inicio)}–${fmtCorto(i.fecha_fin)})`).join(", ") });
    for (const i of esInterino) hs.push({ nivel: "ADVERTENCIA", mensaje: `Es interino de ${i.titular} en esas fechas: ese interinato quedará EN CONFLICTO y habrá que reasignarlo.` });
    el.innerHTML = `<h3 style="margin-bottom:4px">Impacto en la pizarra</h3>` + listaHallazgos(hs);
  };
  $("#l-per", f).onchange = () => { ponerOrgano(); impacto(); };
  $("#l-ini", f).onchange = () => { if (!$("#l-fin", f).value || $("#l-fin", f).value < $("#l-ini", f).value) $("#l-fin", f).value = $("#l-ini", f).value; impacto(); };
  $("#l-fin", f).onchange = impacto;
  ponerOrgano();
  impacto();

  const zona = $("#l-zona", f), input = $("#l-archivo", f);
  const tomar = async (file) => {
    if (!file) return;
    archivo = file;
    $("#l-archivo-nombre", f).textContent = `Seleccionado: ${file.name} (${Math.ceil(file.size / 1024)} KB)`;
    if (file.name.toLowerCase().endsWith(".eml")) {
      const d = leerEml(await file.text());
      if (d.remitente && !$("#l-rem", f).value) $("#l-rem", f).value = d.remitente;
      if (d.asunto && !$("#l-asu", f).value) $("#l-asu", f).value = d.asunto;
      if (d.fecha && !$("#l-fcor", f).value) $("#l-fcor", f).value = aLocal(d.fecha);
      toast("Datos del correo completados. Revíselos antes de guardar.");
    }
  };
  zona.onclick = () => input.click();
  zona.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
  input.onchange = () => tomar(input.files[0]);
  zona.ondragover = (e) => { e.preventDefault(); zona.classList.add("encima"); };
  zona.ondragleave = () => zona.classList.remove("encima");
  zona.ondrop = (e) => { e.preventDefault(); zona.classList.remove("encima"); tomar(e.dataTransfer.files[0]); };

  async function guardar(yAsignar) {
    if (!f.reportValidity()) return false;
    const org = $(`[name=org]:checked`, f);
    if (!org) { toast("Indique quién aprobó la licencia."); return false; }
    const fcor = $("#l-fcor", f).value;
    const cuerpo = {
      personal_id: +$("#l-per", f).value, tipo_licencia_id: +$("#l-tipo", f).value,
      fecha_inicio: $("#l-ini", f).value, fecha_fin: $("#l-fin", f).value, organo_aprobador: org.value,
      nro_resolucion: $("#l-res", f).value, correo_remitente: $("#l-rem", f).value, correo_asunto: $("#l-asu", f).value,
      correo_fecha: fcor ? new Date(fcor).toISOString() : null, enlace_externo: $("#l-enl", f).value,
      observaciones: $("#l-obs", f).value,
    };
    try {
      let r;
      if (existente) r = await api("PUT", `/api/licencias/${existente.id}`, { ...cuerpo, version: existente.version });
      else r = await api("POST", "/api/licencias", cuerpo);
      if (archivo) {
        const fd = new FormData();
        fd.append("archivo", archivo);
        try { await api("POST", `/api/licencias/${r.id}/adjunto`, fd); }
        catch (e) { toast("La licencia se guardó, pero el adjunto no: " + detalleError(e.data), 7000); }
      }
      await recargar();
      if (r.avisos?.length) {
        modal($("#modal2"), { titulo: "Licencia guardada — revise", cuerpo: listaHallazgos(r.avisos), pie: [{ texto: "Entendido", clase: "primario" }] });
      } else toast("Licencia guardada.");
      if (yAsignar) setTimeout(() => formInterinato({ titular_id: cuerpo.personal_id, fecha_inicio: cuerpo.fecha_inicio, fecha_fin: cuerpo.fecha_fin, licencia_id: r.id }), 0);
    } catch (e) { mostrarError(e); return false; }
  }
}

async function verLicencia(id) {
  let l;
  try { l = await api("GET", `/api/licencias/${id}`); } catch (e) { return mostrarError(e); }
  const html = `<dl class="detalle">
    <dt>Funcionario</dt><dd><b>${esc(l.nombre_completo)}</b> — ${esc(l.despacho)}</dd>
    <dt>Tipo</dt><dd>${esc(l.tipo)} <span class="chip ${l.estado}">${l.estado}</span></dd>
    <dt>Período</dt><dd>${fmt(l.fecha_inicio)} al ${fmt(l.fecha_fin)} <span class="ayuda">${contarDias(l.fecha_inicio, l.fecha_fin)}</span></dd>
    <dt>Aprobada por</dt><dd>${l.organo_aprobador === "CONSEJO" ? "Consejo de Administración" : "RRHH"}${l.nro_resolucion ? " · Res. " + esc(l.nro_resolucion) : ""}</dd>
    <dt>Correo</dt><dd>${esc(l.correo_remitente || "—")}${l.correo_fecha ? " · " + fmtHora(l.correo_fecha) : ""}<br>${esc(l.correo_asunto || "")}</dd>
    <dt>Respaldo</dt><dd>${l.adjunto_nombre ? `<a href="/api/licencias/${l.id}/adjunto" target="_blank" rel="noopener">📎 ${esc(l.adjunto_nombre)}</a>` : "—"}
      ${l.enlace_externo ? `<br><a href="${esc(l.enlace_externo)}" target="_blank" rel="noopener noreferrer">🔗 Enlace externo</a>` : ""}</dd>
    <dt>Cubierto por</dt><dd>${l.interinatos.length ? l.interinatos.map((i) => `${esc(i.interino)} (${fmtCorto(i.fecha_inicio)}–${fmtCorto(i.fecha_fin)})${i.estado === "EN_CONFLICTO" ? " ⚡" : ""}`).join("<br>") : "<b style='color:var(--sin-cubrir)'>⚠ Sin interino asignado</b>"}</dd>
    ${l.observaciones ? `<dt>Observaciones</dt><dd>${esc(l.observaciones)}</dd>` : ""}
    ${l.motivo_anulacion ? `<dt>Motivo de anulación</dt><dd>${esc(l.motivo_anulacion)}</dd>` : ""}
    <dt>Registro</dt><dd class="ayuda">Cargada por ${esc(l.creado_por_nombre || "—")} el ${fmtHora(l.creado_en)}${l.modificado_en ? ` · modificada por ${esc(l.modificado_por_nombre || "—")} el ${fmtHora(l.modificado_en)}` : ""}</dd>
  </dl>`;
  const pie = [{ texto: "Cerrar" }];
  if (l.estado === "VIGENTE") {
    pie.unshift({ texto: "Anular", clase: "peligro", accion: () => anular("licencias", l) });
    pie.push({ texto: "Editar", accion: () => { setTimeout(() => formLicencia({}, l), 0); } });
    pie.push({ texto: "Asignar interino", clase: "primario", accion: () => { setTimeout(() => formInterinato({ titular_id: l.personal_id, fecha_inicio: l.fecha_inicio, fecha_fin: l.fecha_fin, licencia_id: l.id }), 0); } });
  }
  modal($("#modal"), { titulo: `Licencia #${l.id}`, cuerpo: html, pie });
}

function anular(tabla, reg) {
  const html = `<p>Los registros no se borran: quedan anulados y visibles en la auditoría.</p>
    <label for="motivo-anul">Motivo de la anulación (obligatorio)</label><textarea id="motivo-anul"></textarea>`;
  modal($("#modal2"), {
    titulo: tabla === "licencias" ? "Anular licencia" : "Anular interinato", cuerpo: html,
    pie: [{ texto: "Cancelar" }, { texto: "Anular", clase: "primario", accion: async () => {
      const motivo = $("#motivo-anul").value.trim();
      if (motivo.length < 3) { toast("Indique el motivo."); return false; }
      try {
        await api("POST", `/api/${tabla}/${reg.id}/anular`, { motivo, version: reg.version });
        $("#modal").close();
        toast("Registro anulado.");
        await recargar();
      } catch (e) { $("#modal2").close(); mostrarError(e); return false; }
    } }],
  });
  return false;
}

// ── Interinatos ───────────────────────────────────────────────────────
async function formInterinato(ini = {}, existente = null) {
  const v = existente || ini;
  const pm = personaPorId();
  let elegido = existente ? existente.interino_id : null;
  let licenciaId = v.licencia_id ?? null;
  let modo = v.vacante_id ? "vacante" : "persona";
  let vacantes = [];
  try { vacantes = await api("GET", "/api/vacantes?solo_vigentes=true"); } catch (e) { /* sin vacantes */ }
  if (v.vacante_id && !vacantes.some((x) => x.id === v.vacante_id)) {
    try { vacantes.push(await api("GET", `/api/vacantes/${v.vacante_id}`)); } catch (e) { /* ya no existe */ }
  }
  const opcionesVac = `<option value="">— Seleccione —</option>` + vacantes.map((x) =>
    `<option value="${x.id}" ${x.id === v.vacante_id ? "selected" : ""}>${esc(x.cargo)}${x.secretaria ? " · Sria. " + esc(x.secretaria) : ""} — ${esc(conTurno(x.despacho, x.turno))}</option>`).join("");
  const html = `<form class="form" id="f-int" autocomplete="off">
    <label>Cubre a</label>
    <div class="fila-campos">
      <label><input type="radio" name="modo" value="persona" ${modo === "persona" ? "checked" : ""}> Una persona ausente</label>
      <label><input type="radio" name="modo" value="vacante" ${modo === "vacante" ? "checked" : ""} ${vacantes.length ? "" : "disabled"}> Un puesto vacante</label>
      ${vacantes.length ? "" : `<span class="ayuda">(no hay puestos vacantes cargados: se cargan en Administración → Vacantes)</span>`}</div>
    <label class="req fila-persona" for="i-tit">Titular (ausente)</label>
    <select id="i-tit" class="fila-persona">${opcionesPersonal(v.titular_id)}</select>
    <label class="req fila-vacante" for="i-vac">Puesto vacante</label>
    <select id="i-vac" class="fila-vacante">${opcionesVac}</select>
    <label class="req">Período</label>
    <div class="fila-campos">Desde <input type="date" id="i-ini" required value="${esc(v.fecha_inicio || "")}">
      Hasta <input type="date" id="i-fin" required value="${esc(v.fecha_fin || "")}"></div>
    <label>Motivo</label><div id="i-motivo" class="ayuda"></div>
    <div class="full" id="i-generales"></div>
    <label class="req">Interino</label>
    <div><input type="search" id="i-buscar" placeholder="Filtrar candidatos…" style="width:100%;margin-bottom:6px">
      <div class="candidatos" id="i-cand"><div class="vacio">Elija a quién cubre y las fechas.</div></div>
      <div class="ayuda">Solo se listan funcionarios del mismo cargo. Primero los disponibles; entre ellos, los del mismo despacho o turno y luego los de la misma localidad.</div></div>
    <label for="i-acto">Nº de acto de designación</label><input type="text" id="i-acto" value="${esc(v.acto_designacion || "")}">
    <label for="i-obs">Observaciones</label><textarea id="i-obs">${esc(v.observaciones || "")}</textarea>
  </form>`;
  const { cuerpo } = modal($("#modal"), {
    titulo: existente ? `Editar interinato #${existente.id}` : "Asignar interino", cuerpo: html,
    pie: [{ texto: "Cancelar" }, { texto: existente ? "Guardar cambios" : "Asignar", clase: "primario", accion: () => guardar(false) }],
  });
  const f = $("#f-int", cuerpo);
  let datosCand = null, pedido = 0;

  const mostrarModo = () => {
    $$(".fila-persona", f).forEach((e) => (e.hidden = modo !== "persona"));
    $$(".fila-vacante", f).forEach((e) => (e.hidden = modo !== "vacante"));
    $("#i-tit", f).required = modo === "persona";
    $("#i-vac", f).required = modo === "vacante";
  };
  const motivo = () => {
    const a = $("#i-ini", f).value, b = $("#i-fin", f).value;
    if (modo === "vacante") {
      licenciaId = null;
      const x = vacantes.find((y) => y.id === +$("#i-vac", f).value);
      $("#i-motivo", f).textContent = x ? `Puesto vacante desde el ${fmt(x.fecha_desde)}${x.fecha_hasta ? " hasta el " + fmt(x.fecha_hasta) : " (sin fecha de fin)"}` : "";
      return;
    }
    const tid = +$("#i-tit", f).value;
    const l = E.datos.licencias.find((x) => x.id === licenciaId) ||
              E.datos.licencias.find((x) => x.personal_id === tid && x.fecha_inicio <= b && x.fecha_fin >= a);
    licenciaId = l && l.personal_id === tid ? l.id : null;
    $("#i-motivo", f).textContent = licenciaId ? `Licencia ${l.tipo} del ${fmt(l.fecha_inicio)} al ${fmt(l.fecha_fin)}` : "Sin licencia vinculada en el período visible.";
  };
  const pintarCand = () => {
    const el = $("#i-cand", f);
    if (!datosCand) return;
    const q = $("#i-buscar", f).value.trim().toLowerCase();
    const cs = datosCand.candidatos.filter((c) => !q || (c.nombre_completo + c.despacho).toLowerCase().includes(q));
    if (!cs.length) { el.innerHTML = `<div class="vacio">No hay candidatos.</div>`; return; }
    const etiqueta = { DISPONIBLE: "Disponible", AVISO: "Con aviso", BLOQUEADO: "No disponible" };
    el.innerHTML = cs.map((c) => `<label class="candidato ${c.estado}">
      <input type="radio" name="cand" value="${c.id}" ${c.estado === "BLOQUEADO" ? "disabled" : ""} ${c.id === elegido ? "checked" : ""}>
      <span><b>${esc(c.nombre_completo)}</b> — ${esc(conTurno(c.despacho, c.turno))}${c.secretaria ? " · Sria. " + esc(c.secretaria) : ""}${c.mismo_despacho ? ` <span class="chip VIGENTE">mismo despacho</span>` : ""}<br>
        ${c.hallazgos.map((h) => `<span class="motivo">${h.nivel === "BLOQUEO" ? "✖" : h.nivel === "ADVERTENCIA" ? "⚠" : "ℹ️"} ${esc(h.mensaje)}</span>`).join("<br>")}</span>
      <span class="estado">${etiqueta[c.estado]}</span></label>`).join("");
    $$("[name=cand]", el).forEach((r) => (r.onchange = () => (elegido = +r.value)));
  };
  const cargarCand = async () => {
    const a = $("#i-ini", f).value, b = $("#i-fin", f).value;
    const id = modo === "vacante" ? +$("#i-vac", f).value : +$("#i-tit", f).value;
    motivo();
    if (!id || !a || !b || b < a) { $("#i-cand", f).innerHTML = `<div class="vacio">Elija a quién cubre y las fechas.</div>`; $("#i-generales", f).innerHTML = ""; return; }
    const n = ++pedido;
    $("#i-cand", f).innerHTML = `<div class="vacio">Verificando disponibilidad…</div>`;
    try {
      const quien = modo === "vacante" ? `vacante_id=${id}` : `titular_id=${id}`;
      const d = await api("GET", `/api/disponibilidad?${quien}&desde=${a}&hasta=${b}${existente ? "&excluir_id=" + existente.id : ""}`);
      if (n !== pedido) return;
      datosCand = d;
      $("#i-generales", f).innerHTML = d.generales.length ? listaHallazgos(d.generales) : "";
      if (!d.candidatos.some((c) => c.id === elegido && c.estado !== "BLOQUEADO")) elegido = existente && d.candidatos.some((c) => c.id === elegido) ? elegido : null;
      pintarCand();
    } catch (e) { mostrarError(e); }
  };
  $$("[name=modo]", f).forEach((r) => (r.onchange = () => { modo = r.value; elegido = null; licenciaId = null; mostrarModo(); cargarCand(); }));
  $("#i-tit", f).onchange = () => { licenciaId = null; elegido = null; cargarCand(); };
  $("#i-vac", f).onchange = () => {
    elegido = null;
    const x = vacantes.find((y) => y.id === +$("#i-vac", f).value);
    if (x && !$("#i-ini", f).value) $("#i-ini", f).value = x.fecha_desde > E.hoy ? x.fecha_desde : E.hoy;
    if (x && x.fecha_hasta && !$("#i-fin", f).value) $("#i-fin", f).value = x.fecha_hasta;
    cargarCand();
  };
  $("#i-ini", f).onchange = () => { if (!$("#i-fin", f).value || $("#i-fin", f).value < $("#i-ini", f).value) $("#i-fin", f).value = $("#i-ini", f).value; cargarCand(); };
  $("#i-fin", f).onchange = cargarCand;
  $("#i-buscar", f).oninput = pintarCand;
  mostrarModo();
  cargarCand();

  async function guardar(confirmado) {
    if (!f.reportValidity()) return false;
    if (!elegido) { toast("Elija un interino de la lista."); return false; }
    const cuerpo = {
      titular_id: modo === "persona" ? +$("#i-tit", f).value : null,
      vacante_id: modo === "vacante" ? +$("#i-vac", f).value : null,
      interino_id: elegido, licencia_id: modo === "persona" ? licenciaId : null,
      fecha_inicio: $("#i-ini", f).value, fecha_fin: $("#i-fin", f).value,
      acto_designacion: $("#i-acto", f).value, observaciones: $("#i-obs", f).value,
      confirmar_advertencias: confirmado,
    };
    try {
      const r = existente
        ? await api("PUT", `/api/interinatos/${existente.id}`, { ...cuerpo, version: existente.version })
        : await api("POST", "/api/interinatos", cuerpo);
      $("#modal").close();
      await recargar();
      const nombre = pm.get(elegido)?.nombre_completo || "";
      toast(`Interinato guardado: ${nombre}.` + (r.avisos?.length ? " " + r.avisos.map((a) => a.mensaje).join(" ") : ""), 6000);
    } catch (e) {
      if (e.status === 428) {
        const ok = await confirmar("Confirme para continuar", listaHallazgos(e.data.hallazgos) +
          `<p class="ayuda">Si confirma, el aviso queda registrado en la auditoría con su usuario.</p>`, "Confirmar y guardar");
        if (ok) await guardar(true);
        return false;
      }
      mostrarError(e);
      return false;
    }
    return false;
  }
}

async function verInterinato(id) {
  let i;
  try { i = await api("GET", `/api/interinatos/${id}`); } catch (e) { return mostrarError(e); }
  const cubre = i.vacante_id
    ? `<dt>Puesto vacante</dt><dd><b>${esc(i.cargo)}${i.vacante_secretaria ? " · Sria. " + esc(i.vacante_secretaria) : ""}</b> — ${esc(i.despacho_titular)}</dd>`
    : `<dt>Titular (ausente)</dt><dd><b>${esc(i.titular)}</b> — ${esc(i.despacho_titular)}</dd>`;
  const html = `${i.estado === "EN_CONFLICTO" ? listaHallazgos([{ nivel: "ADVERTENCIA", mensaje: "EN CONFLICTO: el interino tiene una licencia que se cruza con este período. Edite el interinato para cambiar de interino o de fechas, o anúlelo." }]) : ""}
  <dl class="detalle">
    <dt>Cargo</dt><dd>${esc(i.cargo)} <span class="chip ${i.estado}">${i.estado.replace("_", " ")}</span></dd>
    ${cubre}
    <dt>Interino</dt><dd><b>${esc(i.interino)}</b> — ${esc(i.despacho_interino)}</dd>
    <dt>Período</dt><dd>${fmt(i.fecha_inicio)} al ${fmt(i.fecha_fin)}</dd>
    <dt>Acto de designación</dt><dd>${esc(i.acto_designacion || "—")}</dd>
    ${i.observaciones ? `<dt>Observaciones</dt><dd>${esc(i.observaciones)}</dd>` : ""}
    ${i.motivo_anulacion ? `<dt>Motivo de anulación</dt><dd>${esc(i.motivo_anulacion)}</dd>` : ""}
    <dt>Registro</dt><dd class="ayuda">Cargado por ${esc(i.creado_por_nombre || "—")} el ${fmtHora(i.creado_en)}${i.modificado_en ? ` · modificado por ${esc(i.modificado_por_nombre || "—")} el ${fmtHora(i.modificado_en)}` : ""}</dd>
  </dl>`;
  const pie = [{ texto: "Cerrar" }];
  if (i.estado !== "ANULADO") {
    pie.unshift({ texto: "Anular", clase: "peligro", accion: () => anular("interinatos", i) });
    pie.push({ texto: "Editar", clase: "primario", accion: () => { setTimeout(() => formInterinato({}, i), 0); } });
  }
  modal($("#modal"), { titulo: `Interinato #${i.id}`, cuerpo: html, pie });
}

// ── Puestos vacantes ──────────────────────────────────────────────────
async function verVacante(id) {
  let v;
  try { v = await api("GET", `/api/vacantes/${id}`); } catch (e) { return mostrarError(e); }
  const html = `<dl class="detalle">
    <dt>Despacho</dt><dd><b>${esc(conTurno(v.despacho, v.turno))}</b></dd>
    <dt>Cargo vacante</dt><dd>${esc(v.cargo)}${v.secretaria ? " · Sria. " + esc(v.secretaria) : ""}</dd>
    <dt>Vacante</dt><dd>desde el ${fmt(v.fecha_desde)}${v.fecha_hasta ? " hasta el " + fmt(v.fecha_hasta) : " (sigue vacante)"}</dd>
    <dt>A cargo</dt><dd>${v.interinatos.length ? v.interinatos.map((i) => `${esc(i.interino)} (${fmt(i.fecha_inicio)} – ${fmt(i.fecha_fin)})${i.estado === "EN_CONFLICTO" ? " ⚡" : ""}`).join("<br>") : "<b style='color:var(--sin-cubrir)'>⚠ Nadie asignado</b>"}</dd>
    ${v.observaciones ? `<dt>Observaciones</dt><dd>${esc(v.observaciones)}</dd>` : ""}
  </dl>`;
  const pie = [{ texto: "Cerrar" }];
  if (E.yo.rol === "ADMIN") pie.push({ texto: "Editar / cerrar vacante", accion: () => { setTimeout(() => formVacante(v), 0); } });
  pie.push({ texto: "Asignar a cargo", clase: "primario", accion: () => {
    const desde = v.fecha_desde > E.hoy ? v.fecha_desde : E.hoy;
    setTimeout(() => formInterinato({ vacante_id: v.id, fecha_inicio: desde, fecha_fin: v.fecha_hasta || "" }), 0);
  } });
  modal($("#modal"), { titulo: "Puesto vacante", cuerpo: html, pie });
}

function formVacante(v = {}, alGuardar) {
  const despachos = E.cat.despachos.map((d) => [d.id, conTurno(d.nombre, d.turno)]);
  const cargos = E.cat.cargos.map((c) => [c.codigo, c.nombre]);
  formSimple(v.id ? "Editar puesto vacante" : "Nuevo puesto vacante", [
    { k: "despacho_id", t: "Despacho", tipo: "select", opciones: despachos, req: true, num: true },
    { k: "cargo_codigo", t: "Cargo vacante", tipo: "select", opciones: cargos, req: true },
    { k: "secretaria", t: "Secretaría", lista: SRIAS, ayuda: "Opcional. Elija de la lista o escriba otra (Nº 5, Nº 1 bis…)" },
    { k: "fecha_desde", t: "Vacante desde", tipo: "date", req: true },
    { k: "fecha_hasta", t: "Vacante hasta", tipo: "date", ayuda: "Déjelo vacío mientras siga vacante. Complételo cuando se designe a un titular." },
    { k: "observaciones", t: "Observaciones" },
  ], { cargo_codigo: "ACTUARIO", fecha_desde: E.hoy, ...v }, async (d) => {
    await api(v.id ? "PUT" : "POST", v.id ? `/api/vacantes/${v.id}` : "/api/vacantes", { ...d, version: v.version });
    $("#modal").close();
    await recargar();
    if (alGuardar) alGuardar();
  });
}

// ── Exportación .ics ──────────────────────────────────────────────────
function exportar() {
  const hasta = sumar(E.desde, E.largo - 1);
  const html = `<form class="form" id="f-ics">
    <label>Contenido</label><select id="x-per">${opcionesPersonal(null).replace("— Seleccione —", "Toda la circunscripción")}</select>
    <label>Desde</label><input type="date" id="x-ini" value="${E.desde}">
    <label>Hasta</label><input type="date" id="x-fin" value="${hasta}">
    <div class="full ayuda">El archivo .ics se importa en Google Calendar, Outlook o el calendario del teléfono.
      Los eventos son de día completo; las licencias indican quién las cubre.</div>
    <div class="full" id="x-sus"></div>
  </form>`;
  const { cuerpo } = modal($("#modal"), {
    titulo: "Exportar a calendario (.ics)", cuerpo: html,
    pie: [{ texto: "Cerrar" }, { texto: "⇩ Descargar .ics", clase: "primario", accion: () => {
      const per = $("#x-per", cuerpo).value;
      location.href = `/api/exportar.ics?desde=${$("#x-ini", cuerpo).value}&hasta=${$("#x-fin", cuerpo).value}${per ? "&personal_id=" + per : ""}`;
      return false;
    } }],
  });
  $("#x-per", cuerpo).onchange = () => {
    const p = personaPorId().get(+$("#x-per", cuerpo).value);
    const url = p ? `${location.origin}/ics/${p.ics_token}.ics` : "";
    $("#x-sus", cuerpo).innerHTML = p ? `<h3>Suscripción (se actualiza sola)</h3>
      <p class="ayuda">Funciona solo para dispositivos que lleguen a este servidor por la red interna. Comparta este enlace solo con ${esc(p.nombre_completo)}: quien lo tenga ve sus licencias e interinatos.</p>
      <div class="fila-campos"><input type="text" readonly value="${esc(url)}" style="flex:1" id="x-url"><button type="button" class="btn" id="x-copiar">Copiar</button></div>` : "";
    if (p) $("#x-copiar", cuerpo).onclick = async () => {
      try { await navigator.clipboard.writeText(url); toast("Enlace copiado."); }
      catch { $("#x-url", cuerpo).select(); toast("Seleccionado: copie con Ctrl+C."); }
    };
  };
}

// ── Cuenta ────────────────────────────────────────────────────────────
function cambiarClave() {
  const html = `<form class="form" id="f-clave">
    <label for="c-act">Contraseña actual</label><input type="password" id="c-act" autocomplete="current-password" required>
    <label for="c-nue">Nueva contraseña</label><input type="password" id="c-nue" autocomplete="new-password" minlength="8" required>
    <label for="c-rep">Repita la nueva</label><input type="password" id="c-rep" autocomplete="new-password" minlength="8" required></form>`;
  const { cuerpo } = modal($("#modal"), { titulo: "Cambiar contraseña", cuerpo: html, pie: [{ texto: "Cancelar" }, { texto: "Guardar", clase: "primario", accion: async () => {
    const f = $("#f-clave", cuerpo);
    if (!f.reportValidity()) return false;
    if ($("#c-nue", f).value !== $("#c-rep", f).value) { toast("Las contraseñas nuevas no coinciden."); return false; }
    try { await api("POST", "/api/yo/clave", { clave_actual: $("#c-act", f).value, clave_nueva: $("#c-nue", f).value }); toast("Contraseña actualizada."); }
    catch (e) { mostrarError(e); return false; }
  } }] });
}

// ── Administración (solo ADMIN) ───────────────────────────────────────
async function administrar(pestana = "personal") {
  const tabs = { personal: "Personal", despachos: "Despachos", vacantes: "Vacantes", cargos: "Cargos", usuarios: "Usuarios", inhabiles: "Días inhábiles", auditoria: "Auditoría" };
  const { cuerpo } = modal($("#modal"), { titulo: "Administración", ancho: true,
    cuerpo: `<div class="pestanas">${Object.entries(tabs).map(([k, t]) => `<button data-t="${k}" class="${k === pestana ? "activa" : ""}">${t}</button>`).join("")}</div><div id="adm"></div>` });
  $$(".pestanas button", cuerpo).forEach((b) => (b.onclick = () => administrar(b.dataset.t)));
  const el = $("#adm", cuerpo);
  try {
    if (pestana === "personal") await admPersonal(el);
    if (pestana === "despachos") await admDespachos(el);
    if (pestana === "cargos") await admCargos(el);
    if (pestana === "vacantes") await admVacantes(el);
    if (pestana === "usuarios") await admUsuarios(el);
    if (pestana === "inhabiles") await admInhabiles(el);
    if (pestana === "auditoria") await admAuditoria(el);
  } catch (e) { mostrarError(e); }
}

async function refrescarCatalogos() {
  E.cat = await api("GET", "/api/catalogos");
  await recargar();
}

function formSimple(titulo, campos, valores, alGuardar) {
  const html = `<form class="form" id="f-simple">${campos.map((c) => {
    const v = valores[c.k] ?? "";
    let input;
    if (c.tipo === "select") input = `<select id="s-${c.k}" ${c.req ? "required" : ""}>${c.opciones.map(([val, txt]) => `<option value="${esc(val)}" ${String(val) === String(v) ? "selected" : ""}>${esc(txt)}</option>`).join("")}</select>`;
    else if (c.tipo === "check") input = `<label><input type="checkbox" id="s-${c.k}" ${v !== false ? "checked" : ""}> ${esc(c.ayuda || "")}</label>`;
    else input = `<input type="${c.tipo || "text"}" id="s-${c.k}" value="${esc(v)}" ${c.req ? "required" : ""} ${c.min ? `minlength="${c.min}"` : ""} ${c.lista ? `list="dl-${c.k}"` : ""}>${c.lista ? `<datalist id="dl-${c.k}">${c.lista.map((x) => `<option value="${esc(x)}">`).join("")}</datalist>` : ""}${c.ayuda && c.tipo !== "check" ? `<div class="ayuda">${esc(c.ayuda)}</div>` : ""}`;
    return `<label class="${c.req ? "req" : ""}" for="s-${c.k}">${esc(c.t)}</label><div>${input}</div>`;
  }).join("")}</form>`;
  const { cuerpo } = modal($("#modal2"), { titulo, cuerpo: html, pie: [{ texto: "Cancelar" }, { texto: "Guardar", clase: "primario", accion: async () => {
    const f = $("#f-simple", cuerpo);
    if (!f.reportValidity()) return false;
    const datos = {};
    for (const c of campos) {
      const i = $("#s-" + c.k, f);
      datos[c.k] = c.tipo === "check" ? i.checked : c.num ? +i.value : i.value;
    }
    try { await alGuardar(datos); toast("Guardado."); }
    catch (e) { mostrarError(e); return false; }
  } }] });
}

async function admPersonal(el) {
  const ps = await api("GET", "/api/personal");
  const despachos = E.cat.despachos.map((d) => [d.id, `${d.nombre} (${d.localidad})`]);
  const cargos = E.cat.cargos.map((c) => [c.codigo, c.nombre]);
  const editar = (p = {}) => formSimple(p.id ? "Editar funcionario" : "Nuevo funcionario", [
    { k: "nombre_completo", t: "Nombre completo", req: true, min: 3, ayuda: "Formato sugerido: Apellido, Nombre" },
    { k: "cargo_codigo", t: "Cargo", tipo: "select", opciones: cargos, req: true },
    { k: "despacho_id", t: "Despacho", tipo: "select", opciones: despachos, req: true, num: true },
    { k: "secretaria", t: "Secretaría", lista: SRIAS, ayuda: "Opcional. Elija de la lista o escriba otra (Nº 5, Nº 1 bis…)" },
    { k: "email", t: "Correo", tipo: "email" },
    { k: "activo", t: "Estado", tipo: "check", ayuda: "Activo" },
  ], p, async (d) => {
    await api(p.id ? "PUT" : "POST", p.id ? `/api/personal/${p.id}` : "/api/personal", d);
    await refrescarCatalogos();
    administrar("personal");
  });
  el.innerHTML = `<div class="fila-campos" style="margin-bottom:8px"><button class="btn primario" id="a-nuevo">+ Funcionario</button>
    <input type="search" id="a-buscar" placeholder="Buscar…"></div>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Nombre</th><th>Cargo</th><th>Despacho</th><th>Sria.</th><th>Localidad</th><th></th></tr></thead>
    <tbody>${ps.map((p) => `<tr class="${p.activo ? "" : "inactivo"}" data-q="${esc((p.nombre_completo + p.despacho).toLowerCase())}"><td>${esc(p.nombre_completo)}</td><td>${esc(p.cargo)}</td><td>${esc(conTurno(p.despacho, p.turno))}</td><td>${esc(p.secretaria || "—")}</td><td>${esc(p.localidad)}</td>
      <td style="white-space:nowrap">${p.cargo_codigo === "JUEZ" ? `<button class="btn chico primario" data-equipo="${p.despacho_id}" title="Ver y asignar las secretarias de este juez">Secretarías</button> ` : ""}<button class="btn chico" data-id="${p.id}">Editar</button>
        ${p.registros ? "" : `<button class="btn chico peligro" data-borrar="${p.id}" title="Solo para funcionarios sin licencias ni interinatos (por ejemplo, duplicados)">Eliminar</button>`}</td></tr>`).join("")}</tbody></table></div>
    <p class="ayuda">«Eliminar» solo aparece en funcionarios sin licencias ni interinatos (por ejemplo, cargados por error).
      Para quien tiene historial, use «Editar» y desmarque «Activo».</p>`;
  $("#a-nuevo", el).onclick = () => { if (!E.cat.despachos.length) return toast("Primero cargue al menos un despacho."); editar({ activo: true }); };
  $$("[data-equipo]", el).forEach((b) => (b.onclick = () => equipoDespacho(+b.dataset.equipo)));
  $$("[data-borrar]", el).forEach((b) => (b.onclick = async () => {
    const p = ps.find((x) => x.id === +b.dataset.borrar);
    const ok = await confirmar("Eliminar funcionario",
      `<p>¿Eliminar definitivamente a <b>${esc(p.nombre_completo)}</b> (${esc(p.cargo)}, ${esc(conTurno(p.despacho, p.turno))})?</p>
       <p class="ayuda">No tiene licencias ni interinatos, así que no se pierde historial. La eliminación queda registrada en la auditoría.</p>`,
      "Eliminar");
    if (!ok) return;
    try {
      await api("DELETE", `/api/personal/${p.id}`);
      toast(`${p.nombre_completo} fue eliminado.`);
      await refrescarCatalogos();
      administrar("personal");
    } catch (e) { mostrarError(e); }
  }));
  $("#a-buscar", el).oninput = (e) => $$("tbody tr", el).forEach((tr) => (tr.hidden = !tr.dataset.q.includes(e.target.value.toLowerCase())));
  $$("[data-id]", el).forEach((b) => (b.onclick = () => editar(ps.find((p) => p.id === +b.dataset.id))));
}

async function admDespachos(el) {
  const ds = E.cat.despachos;
  const fueros = [...new Set(ds.map((d) => d.fuero))], locs = [...new Set(ds.map((d) => d.localidad))];
  const turnos = [...new Set(["1º Turno", "2º Turno", "3º Turno", "4º Turno", ...ds.map((d) => d.turno).filter(Boolean)])];
  const editar = (d = {}) => formSimple(d.id ? "Editar despacho" : "Nuevo despacho", [
    { k: "nombre", t: "Nombre", req: true, min: 3, ayuda: "Ej.: Juzgado Civil y Comercial 1º Turno - Caacupé" },
    { k: "fuero", t: "Fuero", req: true, lista: fueros },
    { k: "turno", t: "Turno", lista: turnos, ayuda: "Opcional. Permite filtrar la pizarra por turno." },
    { k: "localidad", t: "Localidad", req: true, lista: locs },
    { k: "activo", t: "Estado", tipo: "check", ayuda: "Activo" },
  ], d, async (x) => {
    await api(d.id ? "PUT" : "POST", d.id ? `/api/despachos/${d.id}` : "/api/despachos", x);
    await refrescarCatalogos();
    administrar("despachos");
  });
  el.innerHTML = `<button class="btn primario" id="a-nuevo" style="margin-bottom:8px">+ Despacho</button>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Despacho</th><th>Fuero</th><th>Turno</th><th>Localidad</th><th></th></tr></thead>
    <tbody>${ds.map((d) => `<tr class="${d.activo ? "" : "inactivo"}"><td>${esc(d.nombre)}</td><td>${esc(d.fuero)}</td><td>${esc(d.turno || "—")}</td><td>${esc(d.localidad)}</td>
      <td style="white-space:nowrap"><button class="btn chico primario" data-equipo="${d.id}">Equipo</button>
        <button class="btn chico" data-id="${d.id}">Editar</button>
        ${d.registros ? "" : `<button class="btn chico peligro" data-borrar="${d.id}">Eliminar</button>`}</td></tr>`).join("")}</tbody></table></div>
    <p class="ayuda">«Equipo» muestra y asigna al juez, actuarios, secretarias y ujier del despacho. «Eliminar» aparece solo en
      despachos sin funcionarios ni puestos vacantes.</p>`;
  $("#a-nuevo", el).onclick = () => editar({ activo: true });
  $$("[data-id]", el).forEach((b) => (b.onclick = () => editar(ds.find((d) => d.id === +b.dataset.id))));
  $$("[data-equipo]", el).forEach((b) => (b.onclick = () => equipoDespacho(+b.dataset.equipo)));
  $$("[data-borrar]", el).forEach((b) => (b.onclick = () => {
    const d = ds.find((x) => x.id === +b.dataset.borrar);
    eliminarRegistro(`/api/despachos/${d.id}`, "Eliminar despacho", `el despacho <b>${esc(conTurno(d.nombre, d.turno))}</b>`, async () => {
      await refrescarCatalogos(); administrar("despachos");
    });
  }));
}

/** Confirma y elimina; el servidor vuelve a comprobar que no haya registros asociados. */
async function eliminarRegistro(url, titulo, queHtml, despues) {
  const ok = await confirmar(titulo, `<p>¿Eliminar definitivamente ${queHtml}?</p>
    <p class="ayuda">La eliminación queda registrada en la auditoría.</p>`, "Eliminar");
  if (!ok) return;
  try {
    await api("DELETE", url);
    toast("Eliminado.");
    await despues();
  } catch (e) { mostrarError(e); }
}

/** Equipo de un despacho: juez, actuarios, secretarias (con su Secretaría) y ujier; permite sumar funcionarios. */
async function equipoDespacho(did) {
  let ps;
  try { ps = await api("GET", "/api/personal"); } catch (e) { return mostrarError(e); }
  const d = E.cat.despachos.find((x) => x.id === did);
  const orden = (c) => E.cat.cargos.find((x) => x.codigo === c)?.orden_pizarra ?? 9;
  const equipo = ps.filter((p) => p.despacho_id === did)
    .sort((a, b) => orden(a.cargo_codigo) - orden(b.cargo_codigo) || String(a.secretaria || "~").localeCompare(String(b.secretaria || "~"))
                    || a.nombre_completo.localeCompare(b.nombre_completo));
  const jueces = equipo.filter((p) => p.cargo_codigo === "JUEZ" && p.activo);
  // Si el despacho ya tiene juez titular, no se ofrecen jueces para "agregar" (evita mover al juez por error)
  const otros = ps.filter((p) => p.despacho_id !== did && p.activo && !(jueces.length && p.cargo_codigo === "JUEZ"));
  const srias = SRIAS;
  const selSria = (actual, attrs) => `<span class="sria">Sria. <input type="text" list="dl-srias" ${attrs} value="${esc(actual || "")}"
    placeholder="—" maxlength="20" style="width:96px"></span>`;
  const secretarias = [...new Set(equipo.filter((p) => p.secretaria).map((p) => p.secretaria))].sort();
  let vacs = [];
  try { vacs = (await api("GET", "/api/vacantes?solo_vigentes=true")).filter((v) => v.despacho_id === did); } catch (e) { /* sin vacantes */ }
  const opcionesOtros = E.cat.cargos.map((c) => {
    const xs = otros.filter((p) => p.cargo_codigo === c.codigo);
    return xs.length ? `<optgroup label="${esc(c.nombre)}">${xs.map((p) => `<option value="${p.id}">${esc(p.nombre_completo)} — hoy en ${esc(conTurno(p.despacho, p.turno))}</option>`).join("")}</optgroup>` : "";
  }).join("");
  const html = `<datalist id="dl-srias">${SRIAS.map((x) => `<option value="${esc(x)}">`).join("")}</datalist>
    <p><b>${esc(conTurno(d.nombre, d.turno))}</b> · ${esc(d.fuero)} · ${esc(d.localidad)}</p>
    <p>${jueces.length ? `Juez titular: <b>${jueces.map((j) => esc(j.nombre_completo)).join(", ")}</b>` : `<b style="color:var(--sin-cubrir)">⚠ Este despacho todavía no tiene juez.</b> Agréguelo abajo o con «+ Nuevo funcionario».`}
      · Secretarías: <b>${secretarias.length ? secretarias.map((x) => "Nº " + esc(x).replace(/^Nº\s*/, "")).join(", ") : "ninguna asignada"}</b></p>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Cargo</th><th>Funcionario</th><th>Secretaría</th><th></th></tr></thead><tbody>
    ${equipo.map((p) => `<tr class="${p.activo ? "" : "inactivo"}"><td>${esc(p.cargo)}</td><td>${esc(p.nombre_completo)}${p.activo ? "" : " (dado de baja)"}</td>
      <td>${["ACTUARIO", "SECRETARIO"].includes(p.cargo_codigo) || p.secretaria ? selSria(p.secretaria, `data-sria="${p.id}"`) : "—"}</td><td><button class="btn chico" data-editar="${p.id}">Editar</button></td></tr>`).join("")
      || `<tr><td colspan="4" class="ayuda">Todavía no hay funcionarios en este despacho.</td></tr>`}
    ${vacs.map((v) => `<tr><td>${esc(v.cargo)}</td><td><i>⚪ Puesto vacante</i></td><td>${v.secretaria ? "Sria. " + esc(v.secretaria) : "—"}</td><td></td></tr>`).join("")}
    </tbody></table></div>
    <h3 style="margin:16px 0 6px;font-size:14px">Agregar al equipo</h3>
    <div class="fila-campos"><select id="eq-persona" style="flex:1;min-width:240px"><option value="">— Elija un funcionario de otro despacho —</option>${opcionesOtros}</select>
      ${selSria("", 'id="eq-sria"')}<button class="btn primario" id="eq-agregar">Agregar</button></div>
    <p class="ayuda">Así se asignan las secretarias al juez: elija a cada una, póngale su Secretaría (Nº 1, Nº 2… o escriba otra) y pulse «Agregar».
      La persona pasa a este despacho y deja el anterior. ${jueces.length ? "No se ofrecen jueces porque este despacho ya tiene su juez titular." : ""}
      Para alguien que todavía no está cargado, use «+ Nuevo funcionario».</p>`;
  const titulo = jueces.length ? `Equipo de ${jueces[0].nombre_completo} (Juez) — ${conTurno(d.nombre, d.turno)}` : `Equipo de ${conTurno(d.nombre, d.turno)}`;
  const { cuerpo } = modal($("#modal"), { titulo, ancho: true, cuerpo: html, pie: [
    { texto: "← Volver a Despachos", accion: () => { setTimeout(() => administrar("despachos"), 0); } },
    { texto: "+ Nuevo funcionario", accion: () => { nuevoEnDespacho(); return false; } },
  ] });
  const guardarPersona = async (p, cambios, mensaje) => {
    await api("PUT", `/api/personal/${p.id}`, { nombre_completo: p.nombre_completo, cargo_codigo: p.cargo_codigo,
      despacho_id: p.despacho_id, secretaria: p.secretaria, email: p.email, activo: p.activo, ...cambios });
    toast(mensaje);
    await refrescarCatalogos();
    equipoDespacho(did);
  };
  $$("[data-sria]", cuerpo).forEach((sel) => (sel.onchange = async () => {
    const p = equipo.find((x) => x.id === +sel.dataset.sria);
    const valor = sel.value.trim() || null;
    if (valor === (p.secretaria || null)) return;
    try { await guardarPersona(p, { secretaria: valor }, `Secretaría de ${p.nombre_completo} actualizada.`); }
    catch (e) { mostrarError(e); }
  }));
  $$("[data-editar]", cuerpo).forEach((b) => (b.onclick = () => {
    const p = equipo.find((x) => x.id === +b.dataset.editar);
    formSimple("Editar funcionario", [
      { k: "nombre_completo", t: "Nombre completo", req: true, min: 3 },
      { k: "cargo_codigo", t: "Cargo", tipo: "select", opciones: E.cat.cargos.map((c) => [c.codigo, c.nombre]), req: true },
      { k: "despacho_id", t: "Despacho", tipo: "select", opciones: E.cat.despachos.map((x) => [x.id, conTurno(x.nombre, x.turno)]), req: true, num: true },
      { k: "secretaria", t: "Secretaría", lista: SRIAS },
      { k: "email", t: "Correo", tipo: "email" },
      { k: "activo", t: "Estado", tipo: "check", ayuda: "Activo" },
    ], p, async (x) => { await guardarPersona(p, x, "Funcionario actualizado."); });
  }));
  $("#eq-agregar", cuerpo).onclick = async () => {
    const p = otros.find((x) => x.id === +$("#eq-persona", cuerpo).value);
    if (!p) return toast("Elija un funcionario.");
    const ok = await confirmar("Agregar al equipo", `<p><b>${esc(p.nombre_completo)}</b> (${esc(p.cargo)}) pasa de
      <b>${esc(conTurno(p.despacho, p.turno))}</b> a <b>${esc(conTurno(d.nombre, d.turno))}</b>.</p>
      <p class="ayuda">Sus licencias e interinatos se conservan.</p>`, "Agregar");
    if (!ok) return;
    try { await guardarPersona(p, { despacho_id: did, secretaria: $("#eq-sria", cuerpo).value.trim() || null }, `${p.nombre_completo} se agregó al equipo.`); }
    catch (e) { mostrarError(e); }
  };
  function nuevoEnDespacho() {
    formSimple(`Nuevo funcionario en ${conTurno(d.nombre, d.turno)}`, [
      { k: "nombre_completo", t: "Nombre completo", req: true, min: 3, ayuda: "Formato sugerido: Apellido, Nombre" },
      { k: "cargo_codigo", t: "Cargo", tipo: "select", opciones: E.cat.cargos.map((c) => [c.codigo, c.nombre]), req: true },
      { k: "secretaria", t: "Secretaría", lista: SRIAS, ayuda: "Opcional. Elija de la lista o escriba otra" },
      { k: "email", t: "Correo", tipo: "email" },
    ], { cargo_codigo: "SECRETARIO" }, async (x) => {
      await api("POST", "/api/personal", { ...x, despacho_id: did, activo: true });
      toast("Funcionario agregado.");
      await refrescarCatalogos();
      equipoDespacho(did);
    });
  }
}

async function admVacantes(el) {
  const vs = await api("GET", "/api/vacantes");
  el.innerHTML = `<p class="ayuda">Puestos sin titular (por ejemplo, una Secretaría sin actuaria designada). Quien quede a cargo
      se asigna como un interinato normal, eligiendo «Un puesto vacante». Cuando se designe a un titular, complete
      «Vacante hasta».</p>
    <button class="btn primario" id="a-nuevo" style="margin-bottom:8px">+ Puesto vacante</button>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Despacho</th><th>Cargo</th><th>Secretaría</th><th>Desde</th><th>Hasta</th><th></th></tr></thead>
    <tbody>${vs.map((v) => `<tr class="${v.fecha_hasta && v.fecha_hasta < E.hoy ? "inactivo" : ""}"><td>${esc(conTurno(v.despacho, v.turno))}</td><td>${esc(v.cargo)}</td>
      <td>${esc(v.secretaria || "—")}</td><td>${fmt(v.fecha_desde)}</td><td>${v.fecha_hasta ? fmt(v.fecha_hasta) : "sigue vacante"}</td>
      <td style="white-space:nowrap"><button class="btn chico" data-id="${v.id}">Editar</button>
        ${v.registros ? "" : `<button class="btn chico peligro" data-borrar="${v.id}">Eliminar</button>`}</td></tr>`).join("") || `<tr><td colspan="6" class="ayuda">No hay puestos vacantes cargados.</td></tr>`}</tbody></table></div>
    <p class="ayuda">«Eliminar» aparece solo en puestos que nunca tuvieron a alguien a cargo (por ejemplo, cargados por error).
      Si ya tuvo, complete «Vacante hasta» para cerrarlo.</p>`;
  $$("[data-borrar]", el).forEach((b) => (b.onclick = () => {
    const v = vs.find((x) => x.id === +b.dataset.borrar);
    eliminarRegistro(`/api/vacantes/${v.id}`, "Eliminar puesto vacante",
      `el puesto vacante de <b>${esc(v.cargo)}${v.secretaria ? " (Sria. " + esc(v.secretaria) + ")" : ""}</b> en ${esc(conTurno(v.despacho, v.turno))}`,
      async () => { await recargar(); administrar("vacantes"); });
  }));
  $("#a-nuevo", el).onclick = () => formVacante({}, () => administrar("vacantes"));
  $$("[data-id]", el).forEach((b) => (b.onclick = () => formVacante(vs.find((v) => v.id === +b.dataset.id), () => administrar("vacantes"))));
}

async function admCargos(el) {
  const cs = E.cat.cargos;
  const tope = (c) => (c.max_interinatos_simultaneos == null ? "Sin límite" : String(c.max_interinatos_simultaneos));
  el.innerHTML = `<p class="ayuda">Cuántos despachos puede cubrir a la vez <b>una misma persona</b> de cada cargo,
      además del propio. Los interinatos siguen siendo solo entre pares (Juez↔Juez, Actuario↔Actuario…).</p>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Cargo</th><th>Aprueba sus licencias</th><th>Despachos a la vez</th><th></th></tr></thead>
    <tbody>${cs.map((c) => `<tr><td>${esc(c.nombre)}</td><td>${c.organo_aprobador === "CONSEJO" ? "Consejo de Administración" : "RRHH"}</td>
      <td>${tope(c)}</td><td><button class="btn chico" data-c="${c.codigo}">Cambiar</button></td></tr>`).join("")}</tbody></table></div>`;
  $$("[data-c]", el).forEach((b) => (b.onclick = () => {
    const c = cs.find((x) => x.codigo === b.dataset.c);
    formSimple(`Límite para ${c.nombre}`, [
      { k: "tope", t: "Despachos a la vez", tipo: "number", ayuda: "Déjelo vacío para «sin límite». 1 = solo uno a la vez." },
    ], { tope: c.max_interinatos_simultaneos ?? "" }, async (d) => {
      const n = String(d.tope).trim() === "" ? null : Math.max(1, parseInt(d.tope, 10));
      await api("PUT", `/api/cargos/${c.codigo}`, { max_interinatos_simultaneos: n });
      await refrescarCatalogos();
      administrar("cargos");
    });
  }));
}

async function admUsuarios(el) {
  const us = await api("GET", "/api/usuarios");
  const editar = (u = {}) => formSimple(u.id ? "Editar usuario" : "Nuevo usuario", [
    { k: "usuario", t: "Usuario", req: true, min: 3, ayuda: "Sin espacios, por ejemplo: jramirez" },
    { k: "nombre", t: "Nombre completo", req: true, min: 3 },
    { k: "rol", t: "Rol", tipo: "select", opciones: [["OPERADOR", "Operador (carga licencias e interinatos)"], ["ADMIN", "Administrador (además: personal, usuarios, auditoría)"]], req: true },
    { k: "clave", t: u.id ? "Nueva contraseña" : "Contraseña", tipo: "password", req: !u.id, min: 8, ayuda: u.id ? "Déjela vacía para no cambiarla." : "Mínimo 8 caracteres. Pídale al usuario que la cambie al ingresar." },
    { k: "activo", t: "Estado", tipo: "check", ayuda: "Puede ingresar" },
  ], u, async (d) => {
    if (!d.clave) delete d.clave;
    await api(u.id ? "PUT" : "POST", u.id ? `/api/usuarios/${u.id}` : "/api/usuarios", d);
    administrar("usuarios");
  });
  el.innerHTML = `<button class="btn primario" id="a-nuevo" style="margin-bottom:8px">+ Usuario</button>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Alta</th><th></th></tr></thead>
    <tbody>${us.map((u) => `<tr class="${u.activo ? "" : "inactivo"}"><td>${esc(u.usuario)}</td><td>${esc(u.nombre)}</td><td>${u.rol}</td><td>${fmtHora(u.creado_en)}</td><td style="white-space:nowrap"><button class="btn chico" data-id="${u.id}">Editar</button>
      ${u.registros || u.id === E.yo.id ? "" : `<button class="btn chico peligro" data-borrar="${u.id}">Eliminar</button>`}</td></tr>`).join("")}</tbody></table></div>
    <p class="ayuda">«Eliminar» aparece solo en usuarios que nunca cargaron ni modificaron datos (por ejemplo, creados por error).
      Para quien ya trabajó en el sistema, use «Editar» y desmarque «Puede ingresar»: así se conserva la auditoría.</p>`;
  $$("[data-borrar]", el).forEach((b) => (b.onclick = () => {
    const u = us.find((x) => x.id === +b.dataset.borrar);
    eliminarRegistro(`/api/usuarios/${u.id}`, "Eliminar usuario", `el usuario <b>${esc(u.usuario)}</b> (${esc(u.nombre)})`,
      async () => administrar("usuarios"));
  }));
  $("#a-nuevo", el).onclick = () => editar({ rol: "OPERADOR", activo: true });
  $$("[data-id]", el).forEach((b) => (b.onclick = () => editar(us.find((u) => u.id === +b.dataset.id))));
}

async function admInhabiles(el) {
  const xs = await api("GET", "/api/dias-inhabiles");
  el.innerHTML = `<p class="ayuda">Feriados, feria judicial y asuetos. Se sombrean en la pizarra y no cuentan como días hábiles sin cubrir.</p>
    <form class="fila-campos" id="a-form" style="margin-bottom:10px"><input type="date" id="a-fecha" required>
      <input type="text" id="a-desc" placeholder="Descripción" required> <button class="btn primario">Agregar</button></form>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Fecha</th><th>Descripción</th><th></th></tr></thead>
    <tbody>${xs.map((x) => `<tr><td>${fmt(x.fecha)} (${DIAS[aFecha(x.fecha).getUTCDay()]})</td><td>${esc(x.descripcion)}</td><td><button class="btn chico peligro" data-f="${x.fecha}">Eliminar</button></td></tr>`).join("")}</tbody></table></div>`;
  $("#a-form", el).onsubmit = async (e) => {
    e.preventDefault();
    try { await api("POST", "/api/dias-inhabiles", { fecha: $("#a-fecha", el).value, descripcion: $("#a-desc", el).value }); await recargar(); administrar("inhabiles"); }
    catch (er) { mostrarError(er); }
  };
  $$("[data-f]", el).forEach((b) => (b.onclick = () => {
    const x = xs.find((y) => y.fecha === b.dataset.f);
    eliminarRegistro(`/api/dias-inhabiles/${x.fecha}`, "Eliminar día inhábil", `el día inhábil <b>${fmt(x.fecha)}</b> (${esc(x.descripcion)})`,
      async () => { await recargar(); administrar("inhabiles"); });
  }));
}

async function admAuditoria(el) {
  const xs = await api("GET", "/api/auditoria?limite=300");
  const resumen = (d) => Object.entries(d).filter(([, v]) => v !== null && v !== "").map(([k, v]) => `${k}: ${v}`).join(" · ");
  el.innerHTML = `<p class="ayuda">Últimos 300 cambios. Las advertencias confirmadas muestran qué avisos aceptó el operador.</p>
    <div class="tabla-contenedor"><table class="tabla"><thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Registro</th><th>Datos</th><th>Avisos confirmados</th></tr></thead>
    <tbody>${xs.map((x) => `<tr><td>${fmtHora(x.ts)}</td><td>${esc(x.usuario || "—")}</td><td>${x.accion}</td><td>${x.tabla} #${x.registro_id}</td>
      <td style="max-width:360px">${esc(resumen(x.datos))}</td><td>${(x.advertencias_confirmadas || []).map((h) => esc(h.mensaje)).join("<br>")}</td></tr>`).join("")}</tbody></table></div>`;
}

// ── Modo TV ───────────────────────────────────────────────────────────
function modoTV() {
  const tv = $("#tv");
  const pintar = () => {
    const h = E.hoy, pm = personaPorId();
    const ausentes = E.datos.licencias.filter((l) => l.fecha_inicio <= h && h <= l.fecha_fin)
      .map((l) => ({ l, p: pm.get(l.personal_id), cub: E.datos.interinatos.find((i) => i.titular_id === l.personal_id && i.fecha_inicio <= h && h <= i.fecha_fin) }))
      .filter((x) => x.p);
    const porCargo = E.cat.cargos.map((c) => ({ c, xs: ausentes.filter((x) => x.p.cargo_codigo === c.codigo) }));
    const dt = aFecha(h);
    tv.innerHTML = `<button class="btn salir" id="tv-salir">Salir (Esc)</button>
      <h1>⚖ ${esc(E.yo.circunscripcion)}</h1>
      <div class="fecha">${["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"][dt.getUTCDay()]} ${fmt(h)} · ${ausentes.length} funcionario(s) de licencia hoy</div>
      <div class="columnas">${porCargo.map(({ c, xs }) => `<div class="tarjeta"><h2>${esc(c.nombre)}</h2>
        ${xs.length ? xs.map((x) => `<div class="item"><b>${esc(x.p.nombre_completo)}</b> — ${esc(x.l.tipo)} hasta el ${fmtCorto(x.l.fecha_fin)}
          <small>${esc(x.p.despacho)}</small>
          ${x.cub ? `<span class="ok">✔ Cubre: ${esc(x.cub.interino)}</span>` : `<span class="mal">⚠ SIN INTERINO</span>`}</div>`).join("") : `<div class="item" style="opacity:.6">Sin ausencias</div>`}</div>`).join("")}</div>`;
    $("#tv-salir").onclick = salir;
  };
  const salir = () => { tv.hidden = true; clearInterval(modoTV._t); document.exitFullscreen?.().catch(() => {}); };
  modoTV.salir = salir;
  E.desde = lunesDe(E.hoy);
  recargar().then(() => { pintar(); tv.hidden = false; tv.requestFullscreen?.().catch(() => {}); });
  clearInterval(modoTV._t);
  modoTV._t = setInterval(() => recargar().then(pintar), 5 * 60 * 1000);
}

// ── Eventos ───────────────────────────────────────────────────────────
function conectarEventos() {
  $("#ant").onclick = () => { E.desde = sumar(E.desde, -7); recargar(); };
  $("#sig").onclick = () => { E.desde = sumar(E.desde, 7); recargar(); };
  $("#hoy").onclick = () => { E.desde = lunesDe(E.hoy); recargar(); };
  $("#largo").onchange = (e) => { E.largo = +e.target.value; pref.guardar("largo", E.largo); recargar(); };
  $("#vista").onchange = (e) => { E.vista = e.target.value; pref.guardar("vista", E.vista); dibujarPizarra(); };
  ["#f-cargo", "#f-fuero", "#f-localidad", "#f-turno"].forEach((s) => ($(s).onchange = dibujarPizarra));
  $("#f-novedades").onchange = (e) => { pref.guardar("novedades", e.target.checked); dibujarPizarra(); };
  let t;
  $("#f-buscar").oninput = () => { clearTimeout(t); t = setTimeout(dibujarPizarra, 150); };
  $("#btn-licencia").onclick = () => formLicencia();
  $("#btn-interinato").onclick = () => formInterinato();
  $("#btn-ics").onclick = exportar;
  $("#btn-tv").onclick = modoTV;
  const menu = $("#menu-usuario");
  $("#btn-usuario").onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  document.addEventListener("click", () => (menu.hidden = true));
  $("#m-admin").onclick = () => administrar();
  $("#m-clave").onclick = cambiarClave;
  $("#m-manual").onclick = () => window.open("/manual", "_blank", "noopener");
  $("#m-salir").onclick = async () => { await api("POST", "/api/logout").catch(() => {}); location.href = "/login"; };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#tv").hidden) { modoTV.salir(); return; }
    if ($("#modal").open || $("#modal2").open || !$("#tv").hidden) return;
    if (e.target.matches("input, select, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "l") { e.preventDefault(); formLicencia(); }
    else if (k === "i") { e.preventDefault(); formInterinato(); }
    else if (k === "t") $("#hoy").click();
    else if (e.key === "ArrowLeft") $("#ant").click();
    else if (e.key === "ArrowRight") $("#sig").click();
  });
}

iniciar();
