const STATIC = [
  { key: "server1", title: "Сервер 1" },
  { key: "server2", title: "Сервер 2" },
  { key: "server3", title: "Сервер 3" },
  { key: "server4", title: "Сервер 4 для ИИ" },
];

const ALIAS = {
  queen: "server1",
  main: "server1",
  cell1: "server2",
  cell2: "server3",
  cell3: "server4",
  ai_exit: "server4",
};

export function normalizeSlot(key) {
  const k = String(key || "").trim().toLowerCase();
  return ALIAS[k] || k;
}

export function displayVpnServers(fromApi) {
  const api = Array.isArray(fromApi) ? fromApi : [];
  if (!api.length) return STATIC.map((s) => ({ ...s }));
  const byKey = new Map();
  for (const row of api) {
    const k = normalizeSlot(row.key);
    if (k) byKey.set(k, { ...row, key: k });
  }
  const staticKeys = new Set(STATIC.map((s) => s.key));
  const merged = STATIC.map((stub) => {
    const known = byKey.get(stub.key);
    if (!known) return { ...stub };
    let title = String(known.title || "").trim() || stub.title;
    if (stub.key === "server4" && (!title || title === "Сервер 4" || title === "server4")) {
      title = stub.title;
    }
    return { ...stub, ...known, key: stub.key, title };
  });
  for (const row of api) {
    const k = normalizeSlot(row.key);
    if (k && !staticKeys.has(k)) merged.push({ ...row, key: k });
  }
  return merged;
}

export function selectedTitle(selected, servers) {
  const slot = normalizeSlot(selected) || "server1";
  const list = servers && servers.length ? servers : displayVpnServers(null);
  const hit = list.find((s) => s.key === slot);
  return hit?.title || (slot === "server4" ? "Сервер 4 для ИИ" : `Сервер ${slot.replace("server", "")}`);
}
