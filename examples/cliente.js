// Consumindo o servidor em JavaScript (navegador ou Node 18+).
const API = "http://localhost:8000";

export async function entrar(usuario, senha) {
  const r = await fetch(`${API}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usuario, senha, lembrar: true }),
  });
  if (!r.ok) throw new Error((await r.json()).erro.mensagem);
  return (await r.json()).token;
}

export async function sigaa(token, rota) {
  const r = await fetch(`${API}${rota}`, { headers: { Authorization: `Bearer ${token}` } });
  const corpo = await r.json();
  if (!r.ok) throw Object.assign(new Error(corpo.erro.mensagem), { codigo: corpo.erro.codigo });
  return corpo;
}

// const token = await entrar("fulano", "***");
// const { oficiais, evolucao } = await sigaa(token, "/v1/indices");
