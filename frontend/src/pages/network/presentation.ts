export function readDrillHash(hash: string): {id: string | null; invalid: boolean} {
  const hit = /^#drill=([^&]*)$/.exec(hash);
  if (!hit) return {id:null, invalid: Boolean(hash && hash.startsWith("#drill"))};
  try { const id = decodeURIComponent(hit[1]); return {id: id && id.length <= 1024 && !/[\u0000-\u001f]/.test(id) ? id : null, invalid: !id || id.length > 1024 || /[\u0000-\u001f]/.test(id)}; }
  catch { return {id:null,invalid:true}; }
}
export function resolvedColor(token: string): string {
  const probe = document.createElement("span"); probe.style.color = token; probe.style.display = "none";
  document.body.appendChild(probe); const color = getComputedStyle(probe).color; probe.remove(); return color;
}
