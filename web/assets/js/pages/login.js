import { api, session } from "../api.js";
import { app, go } from "../shell.js";
import { h, icon } from "../ui.js";

export default async function login(ctx) {
  ctx.topbar && null;
  const user = h("input", { name: "username", autocomplete: "username", required: true, placeholder: "admin" });
  const pass = h("input", { name: "password", type: "password", autocomplete: "current-password", required: true, placeholder: "Password" });
  const err = h("div", { class: "err", role: "alert" });
  const submit = h("button", { class: "btn", type: "submit" }, "Sign in", icon("right", 18));
  const demos = h("div", { class: "demo-list" });

  const doLogin = async (u, p) => {
    err.textContent = ""; submit.disabled = true;
    try {
      const r = await api("/api/auth/login", { method: "POST", body: { username: u, password: p } });
      session.set(r); app.user = r.user; app.meta = null;
      go("#/home");
    } catch (e) { err.textContent = e.message; }
    finally { submit.disabled = false; }
  };
  const form = h("form", { onsubmit: (e) => { e.preventDefault(); doLogin(user.value, pass.value); } },
    h("label", { class: "field" }, "Username or student email", user), h("label", { class: "field" }, "Password", pass), err, submit);

  ctx.view.replaceChildren(h("div", { class: "login-wrap" }, h("div", { class: "login-card" },
    h("div", { class: "brand" }, h("span", { class: "badge-sm" }, "TnP"), h("div", {}, h("b", {}, "Placement Atlas"), h("div", { class: "muted" }, "IIIT Bhopal Training and Placement"))),
    h("h1", {}, "Sign in to your placement desk"),
    h("p", { class: "lead" }, "Officers rank candidates, recruiters run their pipeline, students see where they fit."),
    form, demos)));
  user.focus();

  try {
    const d = await api("/api/auth/demo-accounts", { quiet: true });
    demos.append(h("small", { class: "muted" }, "Demo accounts (click to fill)"));
    d.accounts.forEach((a) => demos.append(h("button", { type: "button", onclick: () => { user.value = a.username; pass.value = a.password; doLogin(a.username, a.password); } },
      h("span", {}, h("b", { style: { fontWeight: 500 } }, a.label), h("br"), h("small", {}, a.username)), icon("right", 16))));
  } catch { demos.remove(); }
}
