/* Eris Tunnel - panel front end. Vanilla JS, no build step. */

const state = {
  token: localStorage.getItem('eris_token') || '',
  view: 'dashboard',
  ssh: [],
  backhaul: [],
  keys: [],
  binary: { installed: false, version: '', arch: '' },
  system: null,
  timer: null
};

/* ── utilities ──────────────────────────────────────────────────────── */

function esc(value) {
  return String(value === undefined || value === null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function bytes(n) {
  n = Number(n) || 0;
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(n < 10 ? 2 : 1)) + ' ' + units[i];
}

function rate(n) { return bytes(n) + '/s'; }

function duration(seconds) {
  seconds = Number(seconds) || 0;
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return d + 'd ' + h + 'h';
  if (h) return h + 'h ' + m + 'm';
  return m + 'm';
}

function toast(message, kind) {
  const root = document.getElementById('toast-root');
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || '');
  el.textContent = message;
  root.appendChild(el);
  setTimeout(function () {
    el.style.opacity = '0';
    setTimeout(function () { el.remove(); }, 250);
  }, 3600);
}

async function api(path, options) {
  options = options || {};
  const headers = Object.assign(
    { 'Content-Type': 'application/json' },
    options.headers || {}
  );
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const response = await fetch(path, {
    method: options.method || 'GET',
    headers: headers,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  if (response.status === 401) {
    logout(true);
    throw new Error(t('msg.sessionExpired'));
  }
  const isText = (response.headers.get('content-type') || '').indexOf('text/plain') === 0;
  const payload = isText ? await response.text() : await response.json().catch(function () { return {}; });
  if (!response.ok) {
    throw new Error((payload && payload.detail) || (typeof payload === 'string' ? payload : t('msg.error')));
  }
  return payload;
}

/* ── modal ──────────────────────────────────────────────────────────── */

function openModal(title, bodyHtml, footHtml) {
  const root = document.getElementById('modal-root');
  root.innerHTML =
    '<div class="modal-backdrop">' +
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<div class="modal-head"><h3>' + esc(title) + '</h3><div class="spacer"></div>' +
          '<button class="icon-btn" data-close="1">✕</button></div>' +
        '<div class="modal-body">' + bodyHtml + '</div>' +
        (footHtml ? '<div class="modal-foot">' + footHtml + '</div>' : '') +
      '</div>' +
    '</div>';
  root.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', closeModal);
  });
  root.querySelector('.modal-backdrop').addEventListener('mousedown', function (event) {
    if (event.target === this) closeModal();
  });
  return root.querySelector('.modal');
}

function closeModal() {
  document.getElementById('modal-root').innerHTML = '';
}

document.addEventListener('keydown', function (event) {
  if (event.key === 'Escape') closeModal();
});

function confirmDialog(name, onConfirm) {
  openModal(
    t('common.delete'),
    '<p>' + esc(t('common.confirmDelete', { name: name })) + '</p>',
    '<button class="btn" data-close="1">' + esc(t('common.cancel')) + '</button>' +
    '<button class="btn btn-danger" id="confirm-yes">' + esc(t('common.delete')) + '</button>'
  );
  document.getElementById('confirm-yes').addEventListener('click', function () {
    closeModal();
    onConfirm();
  });
}

/* ── auth ───────────────────────────────────────────────────────────── */

document.getElementById('login-form').addEventListener('submit', async function (event) {
  event.preventDefault();
  const error = document.getElementById('login-error');
  error.textContent = '';
  try {
    const result = await api('/api/login', {
      method: 'POST',
      body: {
        username: document.getElementById('login-username').value,
        password: document.getElementById('login-password').value
      }
    });
    state.token = result.token;
    localStorage.setItem('eris_token', result.token);
    await startPanel();
  } catch (exc) {
    error.textContent = exc.message;
  }
});

document.getElementById('login-lang').addEventListener('click', function () {
  setLang(LANG === 'fa' ? 'en' : 'fa');
  this.textContent = LANG === 'fa' ? 'English' : 'فارسی';
});

document.getElementById('lang-toggle').addEventListener('click', function () {
  setLang(LANG === 'fa' ? 'en' : 'fa');
  this.textContent = LANG === 'fa' ? 'EN' : 'FA';
  render();
});

document.getElementById('logout-btn').addEventListener('click', function () { logout(); });

function logout(silent) {
  state.token = '';
  localStorage.removeItem('eris_token');
  if (state.timer) clearInterval(state.timer);
  document.getElementById('app').classList.add('hidden');
  document.getElementById('login-screen').classList.remove('hidden');
  if (!silent) toast(t('nav.logout'), 'ok');
}

async function startPanel() {
  const me = await api('/api/me');
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('panel-version').textContent = 'v' + me.version;
  state.view = (location.hash || '#dashboard').slice(1);
  if (!['dashboard', 'ssh', 'backhaul', 'keys', 'settings'].includes(state.view)) {
    state.view = 'dashboard';
  }
  await render();
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(function () {
    if (state.view === 'dashboard' && !document.querySelector('.modal-backdrop')) {
      refreshDashboard();
    }
  }, 4000);
}

/* ── routing ────────────────────────────────────────────────────────── */

document.querySelectorAll('.nav-item').forEach(function (item) {
  item.addEventListener('click', function () {
    state.view = item.dataset.view;
    document.getElementById('sidebar').classList.remove('open');
    render();
  });
});

document.getElementById('menu-toggle').addEventListener('click', function () {
  document.getElementById('sidebar').classList.toggle('open');
});

const TITLES = {
  dashboard: 'nav.dashboard',
  ssh: 'ssh.title',
  backhaul: 'bh.title',
  keys: 'keys.title',
  settings: 'set.title'
};

async function render() {
  applyStaticTranslations();
  document.getElementById('lang-toggle').textContent = LANG === 'fa' ? 'EN' : 'FA';
  document.querySelectorAll('.nav-item').forEach(function (item) {
    item.classList.toggle('active', item.dataset.view === state.view);
  });
  document.getElementById('page-title').textContent = t(TITLES[state.view]);
  const view = document.getElementById('view');
  view.innerHTML = '<div class="empty">' + esc(t('common.loading')) + '</div>';
  try {
    if (state.view === 'dashboard') await viewDashboard();
    else if (state.view === 'ssh') await viewSsh();
    else if (state.view === 'backhaul') await viewBackhaul();
    else if (state.view === 'keys') await viewKeys();
    else await viewSettings();
  } catch (exc) {
    view.innerHTML = '<div class="empty">' + esc(exc.message) + '</div>';
  }
}

/* ── dashboard ──────────────────────────────────────────────────────── */

function barClass(percent) {
  return percent >= 90 ? 'bar danger' : percent >= 70 ? 'bar warn' : 'bar';
}

function statCard(label, value, sub, percent) {
  return '<div class="card">' +
    '<div class="stat-label"><span>' + esc(label) + '</span><span>' + esc(sub || '') + '</span></div>' +
    '<div class="stat-value">' + esc(value) + '</div>' +
    (percent === null ? '' :
      '<div class="' + barClass(percent) + '"><i style="width:' + Math.min(100, percent) + '%"></i></div>') +
    '</div>';
}

async function viewDashboard() {
  const [system, overview] = await Promise.all([api('/api/system'), api('/api/overview')]);
  state.system = system;
  document.getElementById('view').innerHTML = dashboardHtml(system, overview);
}

async function refreshDashboard() {
  try {
    const [system, overview] = await Promise.all([api('/api/system'), api('/api/overview')]);
    state.system = system;
    document.getElementById('view').innerHTML = dashboardHtml(system, overview);
  } catch (exc) { /* transient poll failure - keep the last frame */ }
}

function dashboardHtml(s, o) {
  const notices = [];
  if (!s.panel.systemd) {
    notices.push('<div class="notice">' + esc(t('dash.noSystemd')) + '</div>');
  }
  if (!s.panel.sshpass) {
    notices.push('<div class="notice">' + esc(t('ssh.noSshpass')) + '</div>');
  }

  return notices.join('') +
    '<div class="grid grid-4">' +
      statCard(t('dash.cpu'), s.cpu + '%', s.cores + ' ' + t('dash.cores'), s.cpu) +
      statCard(t('dash.memory'), s.memory.percent + '%',
        bytes(s.memory.used) + ' / ' + bytes(s.memory.total), s.memory.percent) +
      statCard(t('dash.disk'), s.disk.percent + '%',
        bytes(s.disk.used) + ' / ' + bytes(s.disk.total), s.disk.percent) +
      '<div class="card">' +
        '<div class="stat-label"><span>' + esc(t('dash.network')) + '</span></div>' +
        '<div class="stat-value" style="font-size:19px">↓ ' + esc(rate(s.network.rx_rate)) + '</div>' +
        '<div class="stat-value" style="font-size:19px;margin-top:-4px">↑ ' + esc(rate(s.network.tx_rate)) + '</div>' +
      '</div>' +
    '</div>' +

    '<div class="grid grid-2" style="margin-top:16px">' +
      '<div class="card">' +
        '<div class="card-head"><h3>' + esc(t('dash.system')) + '</h3></div>' +
        kv(t('dash.hostname'), s.hostname) +
        kv(t('dash.os'), s.os) +
        kv(t('dash.kernel'), s.kernel + ' (' + s.arch + ')') +
        kv(t('dash.uptime'), duration(s.uptime)) +
        kv(t('dash.load'), s.load.join(' / ')) +
        kv(t('dash.connections'), s.connections) +
        kv(t('dash.totalRx'), bytes(s.network.rx)) +
        kv(t('dash.totalTx'), bytes(s.network.tx)) +
      '</div>' +
      '<div class="card">' +
        '<div class="card-head"><h3>' + esc(t('dash.tunnels')) + '</h3></div>' +
        kv(t('dash.sshCount'), o.ssh_total) +
        kv(t('dash.bhCount'), o.backhaul_total) +
        kv(t('dash.running'), o.running) +
        kv(t('dash.stoppedCount'), o.stopped) +
        kv('Backhaul', s.panel.backhaul || '—') +
        kv('Eris Tunnel', 'v' + s.panel.version) +
      '</div>' +
    '</div>';
}

function kv(label, value) {
  return '<div class="kv"><span>' + esc(label) + '</span><span>' + esc(value) + '</span></div>';
}

/* ── shared tunnel table pieces ─────────────────────────────────────── */

function statusBadge(status) {
  const active = (status && status.active) || 'unknown';
  if (active === 'active') return '<span class="badge ok">' + esc(t('common.running')) + '</span>';
  if (active === 'failed') return '<span class="badge down">' + esc(t('common.failed')) + '</span>';
  if (active === 'unknown') return '<span class="badge">' + esc(t('common.unknown')) + '</span>';
  return '<span class="badge idle">' + esc(t('common.stopped')) + '</span>';
}

function actionButtons(kind, tunnel) {
  const running = tunnel.status && tunnel.status.active === 'active';
  return '<div class="row-actions">' +
    (running
      ? '<button class="btn btn-sm" data-act="stop" data-id="' + tunnel.id + '">' + esc(t('common.stop')) + '</button>'
      : '<button class="btn btn-sm" data-act="start" data-id="' + tunnel.id + '">' + esc(t('common.start')) + '</button>') +
    '<button class="btn btn-sm" data-act="restart" data-id="' + tunnel.id + '">' + esc(t('common.restart')) + '</button>' +
    '<button class="btn btn-sm" data-act="logs" data-id="' + tunnel.id + '">' + esc(t('common.logs')) + '</button>' +
    '<button class="btn btn-sm" data-act="edit" data-id="' + tunnel.id + '">' + esc(t('common.edit')) + '</button>' +
    '<button class="btn btn-sm btn-danger" data-act="delete" data-id="' + tunnel.id + '">' + esc(t('common.delete')) + '</button>' +
    '</div>';
}

function bindTunnelActions(kind, list, onEdit) {
  document.querySelectorAll('#view [data-act]').forEach(function (button) {
    button.addEventListener('click', async function () {
      const id = Number(button.dataset.id);
      const tunnel = list.find(function (item) { return item.id === id; });
      const action = button.dataset.act;
      if (action === 'edit') return onEdit(tunnel);
      if (action === 'logs') return showLogs(kind, tunnel);
      if (action === 'delete') {
        return confirmDialog(tunnel.name, async function () {
          try {
            await api('/api/' + kind + '/' + id, { method: 'DELETE' });
            toast(t('msg.deleted'), 'ok');
            render();
          } catch (exc) { toast(exc.message, 'err'); }
        });
      }
      button.disabled = true;
      try {
        const result = await api('/api/' + kind + '/' + id + '/' + action, { method: 'POST' });
        if (result.ok === false && result.output) toast(result.output, 'err');
        else toast(t('msg.done'), 'ok');
      } catch (exc) {
        toast(exc.message, 'err');
      }
      setTimeout(render, 700);
    });
  });
}

async function showLogs(kind, tunnel) {
  openModal(
    t('common.logs') + ' — ' + tunnel.name,
    '<pre class="log" id="log-box">' + esc(t('common.loading')) + '</pre>',
    '<button class="btn" id="log-refresh">' + esc(t('common.refresh')) + '</button>' +
    '<button class="btn btn-primary" data-close="1">' + esc(t('common.close')) + '</button>'
  );
  async function load() {
    const box = document.getElementById('log-box');
    try {
      box.textContent = await api('/api/' + kind + '/' + tunnel.id + '/logs?lines=300');
      box.scrollTop = box.scrollHeight;
    } catch (exc) { box.textContent = exc.message; }
  }
  document.getElementById('log-refresh').addEventListener('click', load);
  load();
}

/* ── SSH view ───────────────────────────────────────────────────────── */

function summariseForwards(forwards) {
  return (forwards || []).map(function (f) {
    if (f.type === 'dynamic') return 'SOCKS ' + f.bind + ':' + f.listen_port;
    const arrow = f.type === 'local' ? '→' : '←';
    return (f.type === 'local' ? 'L' : 'R') + ' ' + f.bind + ':' + f.listen_port +
      ' ' + arrow + ' ' + f.dest_host + ':' + f.dest_port;
  }).map(function (text) { return '<span class="tag mono">' + esc(text) + '</span>'; }).join('');
}

async function viewSsh() {
  const [tunnels, keys] = await Promise.all([api('/api/ssh'), api('/api/keys')]);
  state.ssh = tunnels;
  state.keys = keys;

  const rows = tunnels.map(function (tunnel) {
    return '<tr>' +
      '<td><strong>' + esc(tunnel.name) + '</strong>' +
        (tunnel.note ? '<div class="muted" style="font-size:12px">' + esc(tunnel.note) + '</div>' : '') + '</td>' +
      '<td class="mono">' + esc(tunnel.user + '@' + tunnel.host + ':' + tunnel.port) + '</td>' +
      '<td>' + summariseForwards(tunnel.forwards) + '</td>' +
      '<td>' + statusBadge(tunnel.status) + '</td>' +
      '<td>' + actionButtons('ssh', tunnel) + '</td>' +
    '</tr>';
  }).join('');

  document.getElementById('view').innerHTML =
    '<div class="card-head">' +
      '<button class="btn btn-primary" id="ssh-new">+ ' + esc(t('ssh.new')) + '</button>' +
      '<button class="btn btn-ghost" id="ssh-refresh">↻ ' + esc(t('common.refresh')) + '</button>' +
    '</div>' +
    (tunnels.length
      ? '<div class="table-wrap"><table><thead><tr>' +
          '<th>' + esc(t('common.name')) + '</th>' +
          '<th>' + esc(t('ssh.target')) + '</th>' +
          '<th>' + esc(t('ssh.rules')) + '</th>' +
          '<th>' + esc(t('common.status')) + '</th>' +
          '<th>' + esc(t('common.actions')) + '</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>'
      : '<div class="card empty"><span class="big">⇄</span>' + esc(t('ssh.empty')) +
        '<div class="muted" style="margin-top:6px">' + esc(t('ssh.emptyHint')) + '</div></div>');

  document.getElementById('ssh-new').addEventListener('click', function () { sshForm(null); });
  document.getElementById('ssh-refresh').addEventListener('click', render);
  bindTunnelActions('ssh', tunnels, sshForm);
}

function ruleRow(rule) {
  rule = rule || { type: 'local', bind: '127.0.0.1', listen_port: '', dest_host: '127.0.0.1', dest_port: '' };
  const dynamic = rule.type === 'dynamic';
  return '<div class="rule-row">' +
    '<select class="r-type">' +
      '<option value="local"' + (rule.type === 'local' ? ' selected' : '') + '>' + esc(t('ssh.typeLocal')) + '</option>' +
      '<option value="remote"' + (rule.type === 'remote' ? ' selected' : '') + '>' + esc(t('ssh.typeRemote')) + '</option>' +
      '<option value="dynamic"' + (dynamic ? ' selected' : '') + '>' + esc(t('ssh.typeDynamic')) + '</option>' +
    '</select>' +
    '<input class="r-bind" placeholder="' + esc(t('ssh.bind')) + '" value="' + esc(rule.bind || '127.0.0.1') + '">' +
    '<input class="r-lport" type="number" min="1" max="65535" placeholder="' + esc(t('ssh.listenPort')) + '" value="' + esc(rule.listen_port) + '">' +
    '<input class="r-dhost" placeholder="' + esc(t('ssh.destHost')) + '" value="' + esc(rule.dest_host || '127.0.0.1') + '"' + (dynamic ? ' disabled' : '') + '>' +
    '<input class="r-dport" type="number" min="1" max="65535" placeholder="' + esc(t('ssh.destPort')) + '" value="' + esc(rule.dest_port) + '"' + (dynamic ? ' disabled' : '') + '>' +
    '<button type="button" class="btn btn-sm rm">✕</button>' +
  '</div>';
}

function bindRuleRow(row) {
  row.querySelector('.rm').addEventListener('click', function () { row.remove(); });
  row.querySelector('.r-type').addEventListener('change', function () {
    const dynamic = this.value === 'dynamic';
    row.querySelector('.r-dhost').disabled = dynamic;
    row.querySelector('.r-dport').disabled = dynamic;
  });
}

function sshForm(tunnel) {
  const editing = Boolean(tunnel);
  const data = tunnel || {
    name: '', host: '', port: 22, user: 'root', auth: 'password',
    key_name: '', forwards: [], keepalive: 30, compression: false, options: [], note: ''
  };
  const keyOptions = state.keys.length
    ? state.keys.map(function (key) {
        return '<option value="' + esc(key.name) + '"' + (key.name === data.key_name ? ' selected' : '') + '>' + esc(key.name) + '</option>';
      }).join('')
    : '<option value="">' + esc(t('ssh.noKeys')) + '</option>';

  const body =
    '<div class="field"><label>' + esc(t('common.name')) + '</label>' +
      '<input id="f-name" value="' + esc(data.name) + '" placeholder="tokyo-relay" maxlength="32"></div>' +

    '<fieldset><legend>' + esc(t('ssh.server')) + '</legend>' +
      '<div class="form-grid">' +
        '<div class="field"><label>' + esc(t('ssh.host')) + '</label><input id="f-host" value="' + esc(data.host) + '" placeholder="1.2.3.4"></div>' +
        '<div class="field"><label>' + esc(t('ssh.port')) + '</label><input id="f-port" type="number" value="' + esc(data.port) + '"></div>' +
        '<div class="field"><label>' + esc(t('ssh.user')) + '</label><input id="f-user" value="' + esc(data.user) + '"></div>' +
        '<div class="field"><label>' + esc(t('ssh.auth')) + '</label><select id="f-auth">' +
          '<option value="password"' + (data.auth === 'password' ? ' selected' : '') + '>' + esc(t('ssh.authPassword')) + '</option>' +
          '<option value="key"' + (data.auth === 'key' ? ' selected' : '') + '>' + esc(t('ssh.authKey')) + '</option>' +
        '</select></div>' +
      '</div>' +
      '<div class="field" id="wrap-password"><label>' + esc(t('ssh.password')) + '</label>' +
        '<input id="f-password" type="password" autocomplete="new-password" placeholder="' + (editing ? esc(t('ssh.passwordKeep')) : '') + '">' +
        '<div class="hint">' + esc(t('ssh.passwordKeep')) + '</div></div>' +
      '<div class="field hidden" id="wrap-key"><label>' + esc(t('ssh.key')) + '</label>' +
        '<select id="f-key">' + keyOptions + '</select></div>' +
    '</fieldset>' +

    '<fieldset><legend>' + esc(t('ssh.forwards')) + '</legend>' +
      '<div id="rules">' + (data.forwards.length ? data.forwards.map(ruleRow).join('') : ruleRow(null)) + '</div>' +
      '<button type="button" class="btn btn-sm" id="add-rule">+ ' + esc(t('ssh.addRule')) + '</button>' +
      '<div class="hint" style="margin-top:8px">' + esc(t('ssh.remoteHint')) + '</div>' +
    '</fieldset>' +

    '<fieldset><legend>' + esc(t('ssh.advanced')) + '</legend>' +
      '<div class="form-grid">' +
        '<div class="field"><label>' + esc(t('ssh.keepalive')) + '</label><input id="f-keepalive" type="number" value="' + esc(data.keepalive) + '"></div>' +
        '<div class="field"><label>' + esc(t('common.note')) + ' (' + esc(t('common.optional')) + ')</label><input id="f-note" value="' + esc(data.note || '') + '" maxlength="200"></div>' +
      '</div>' +
      '<div class="check"><input type="checkbox" id="f-compression"' + (data.compression ? ' checked' : '') + '>' +
        '<label for="f-compression">' + esc(t('ssh.compression')) + '</label></div>' +
      '<div class="field"><label>' + esc(t('ssh.options')) + '</label>' +
        '<textarea id="f-options" placeholder="GatewayPorts=yes">' + esc((data.options || []).join('\n')) + '</textarea>' +
        '<div class="hint">' + esc(t('ssh.optionsHint')) + '</div></div>' +
      (editing ? '' : '<div class="check"><input type="checkbox" id="f-autostart" checked>' +
        '<label for="f-autostart">' + esc(t('common.autostart')) + '</label></div>') +
    '</fieldset>' +
    '<div class="form-error" id="f-error"></div>';

  openModal(
    editing ? t('ssh.edit') : t('ssh.new'),
    body,
    '<button class="btn" id="f-test">' + esc(t('common.test')) + '</button>' +
    '<div class="spacer"></div>' +
    '<button class="btn" data-close="1">' + esc(t('common.cancel')) + '</button>' +
    '<button class="btn btn-primary" id="f-save">' + esc(t('common.save')) + '</button>'
  );

  function syncAuth() {
    const key = document.getElementById('f-auth').value === 'key';
    document.getElementById('wrap-key').classList.toggle('hidden', !key);
    document.getElementById('wrap-password').classList.toggle('hidden', key);
  }
  document.getElementById('f-auth').addEventListener('change', syncAuth);
  syncAuth();

  document.querySelectorAll('#rules .rule-row').forEach(bindRuleRow);
  document.getElementById('add-rule').addEventListener('click', function () {
    const holder = document.getElementById('rules');
    holder.insertAdjacentHTML('beforeend', ruleRow(null));
    bindRuleRow(holder.lastElementChild);
  });

  function collect() {
    const forwards = [];
    document.querySelectorAll('#rules .rule-row').forEach(function (row) {
      const type = row.querySelector('.r-type').value;
      const entry = {
        type: type,
        bind: row.querySelector('.r-bind').value.trim() || '127.0.0.1',
        listen_port: row.querySelector('.r-lport').value
      };
      if (type !== 'dynamic') {
        entry.dest_host = row.querySelector('.r-dhost').value.trim() || '127.0.0.1';
        entry.dest_port = row.querySelector('.r-dport').value;
      }
      if (entry.listen_port) forwards.push(entry);
    });
    return {
      name: document.getElementById('f-name').value.trim(),
      host: document.getElementById('f-host').value.trim(),
      port: document.getElementById('f-port').value,
      user: document.getElementById('f-user').value.trim(),
      auth: document.getElementById('f-auth').value,
      key_name: document.getElementById('f-key') ? document.getElementById('f-key').value : '',
      password: document.getElementById('f-password').value,
      forwards: forwards,
      keepalive: document.getElementById('f-keepalive').value,
      compression: document.getElementById('f-compression').checked,
      options: document.getElementById('f-options').value.split('\n').map(function (line) {
        return line.trim();
      }).filter(Boolean),
      note: document.getElementById('f-note').value,
      autostart: document.getElementById('f-autostart') ? document.getElementById('f-autostart').checked : false,
      has_password: data.has_password
    };
  }

  document.getElementById('f-test').addEventListener('click', async function () {
    const button = this;
    const error = document.getElementById('f-error');
    button.disabled = true;
    error.textContent = t('ssh.testing');
    try {
      const result = await api('/api/ssh/test', { method: 'POST', body: collect() });
      error.textContent = result.ok ? '' : t('ssh.testFail') + ': ' + result.output;
      if (result.ok) toast(t('ssh.testOk'), 'ok');
    } catch (exc) {
      error.textContent = exc.message;
    }
    button.disabled = false;
  });

  document.getElementById('f-save').addEventListener('click', async function () {
    const button = this;
    const error = document.getElementById('f-error');
    button.disabled = true;
    error.textContent = '';
    try {
      const payload = collect();
      if (editing) await api('/api/ssh/' + tunnel.id, { method: 'PUT', body: payload });
      else await api('/api/ssh', { method: 'POST', body: payload });
      closeModal();
      toast(t('msg.saved'), 'ok');
      render();
    } catch (exc) {
      error.textContent = exc.message;
      button.disabled = false;
    }
  });
}

/* ── Backhaul view ──────────────────────────────────────────────────── */

async function viewBackhaul() {
  const [tunnels, binary] = await Promise.all([api('/api/backhaul'), api('/api/backhaul/binary')]);
  state.backhaul = tunnels;
  state.binary = binary;

  const rows = tunnels.map(function (tunnel) {
    const address = tunnel.role === 'server' ? tunnel.bind_addr : tunnel.remote_addr;
    return '<tr>' +
      '<td><strong>' + esc(tunnel.name) + '</strong>' +
        (tunnel.note ? '<div class="muted" style="font-size:12px">' + esc(tunnel.note) + '</div>' : '') + '</td>' +
      '<td><span class="tag">' + esc(t('bh.' + tunnel.role)) + '</span></td>' +
      '<td><span class="tag mono">' + esc(tunnel.transport) + '</span></td>' +
      '<td class="mono">' + esc(address) +
        (tunnel.role === 'server' && tunnel.ports && tunnel.ports.length
          ? '<div class="muted" style="font-size:12px">' + esc(tunnel.ports.join(', ')) + '</div>' : '') + '</td>' +
      '<td>' + statusBadge(tunnel.status) + '</td>' +
      '<td>' + actionButtons('backhaul', tunnel) + '</td>' +
    '</tr>';
  }).join('');

  const binaryBar = binary.installed
    ? '<div class="notice ok"><span>' + esc(t('bh.installed')) + ': <b class="mono">' + esc(binary.version) + '</b> · ' + esc(binary.arch) + '</span>' +
      '<div class="spacer"></div><button class="btn btn-sm" id="bh-install">' + esc(t('bh.update')) + '</button></div>'
    : '<div class="notice"><span>' + esc(t('bh.binaryMissing')) + '</span>' +
      '<div class="spacer"></div><button class="btn btn-sm btn-primary" id="bh-install">' + esc(t('bh.install')) + '</button></div>';

  document.getElementById('view').innerHTML = binaryBar +
    '<div class="card-head">' +
      '<button class="btn btn-primary" id="bh-new"' + (binary.installed ? '' : ' disabled') + '>+ ' + esc(t('bh.new')) + '</button>' +
      '<button class="btn btn-ghost" id="bh-refresh">↻ ' + esc(t('common.refresh')) + '</button>' +
    '</div>' +
    (tunnels.length
      ? '<div class="table-wrap"><table><thead><tr>' +
          '<th>' + esc(t('common.name')) + '</th>' +
          '<th>' + esc(t('bh.role')) + '</th>' +
          '<th>' + esc(t('bh.transport')) + '</th>' +
          '<th>' + esc(t('bh.bindAddr')) + '</th>' +
          '<th>' + esc(t('common.status')) + '</th>' +
          '<th>' + esc(t('common.actions')) + '</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>'
      : '<div class="card empty"><span class="big">⇅</span>' + esc(t('bh.empty')) +
        '<div class="muted" style="margin-top:6px">' + esc(t('bh.emptyHint')) + '</div></div>');

  document.getElementById('bh-install').addEventListener('click', async function () {
    const button = this;
    button.disabled = true;
    button.innerHTML = '<span class="spin"></span> ' + esc(t('bh.installing'));
    try {
      const result = await api('/api/backhaul/binary', { method: 'POST' });
      toast(t('bh.installed') + ': ' + result.version, 'ok');
      render();
    } catch (exc) {
      toast(exc.message, 'err');
      button.disabled = false;
      button.textContent = t('bh.install');
    }
  });
  document.getElementById('bh-new').addEventListener('click', function () { backhaulForm(null); });
  document.getElementById('bh-refresh').addEventListener('click', render);
  bindTunnelActions('backhaul', tunnels, backhaulForm);
}

function portRow(value) {
  return '<div class="port-row">' +
    '<input class="p-value mono" value="' + esc(value || '') + '" placeholder="443 / 8080=80 / 2000-2100">' +
    '<button type="button" class="btn btn-sm rm">✕</button></div>';
}

function backhaulForm(tunnel) {
  const editing = Boolean(tunnel);
  const data = Object.assign({
    name: '', role: 'server', transport: 'tcp', token: '', bind_addr: '0.0.0.0:3080',
    remote_addr: '', edge_ip: '', ports: [], accept_udp: false, heartbeat: 40,
    channel_size: 2048, connection_pool: 8, aggressive_pool: false, dial_timeout: 10,
    retry_interval: 3, keepalive_period: 75, nodelay: true, sniffer: false, web_port: 0,
    log_level: 'info', mux_con: 8, mux_version: 1, mux_framesize: 32768,
    mux_receivebuffer: 4194304, mux_streambuffer: 65536, tls_cert: '', tls_key: '', note: ''
  }, tunnel || {});

  const transports = ['tcp', 'tcpmux', 'udp', 'ws', 'wsmux', 'wss', 'wssmux'].map(function (item) {
    return '<option value="' + item + '"' + (data.transport === item ? ' selected' : '') + '>' + item + '</option>';
  }).join('');
  const levels = ['debug', 'info', 'warn', 'error', 'fatal', 'panic'].map(function (item) {
    return '<option value="' + item + '"' + (data.log_level === item ? ' selected' : '') + '>' + item + '</option>';
  }).join('');

  const body =
    '<div class="form-grid">' +
      '<div class="field"><label>' + esc(t('common.name')) + '</label>' +
        '<input id="b-name" value="' + esc(data.name) + '" placeholder="main" maxlength="32"></div>' +
      '<div class="field"><label>' + esc(t('bh.role')) + '</label><select id="b-role">' +
        '<option value="server"' + (data.role === 'server' ? ' selected' : '') + '>' + esc(t('bh.server')) + '</option>' +
        '<option value="client"' + (data.role === 'client' ? ' selected' : '') + '>' + esc(t('bh.client')) + '</option>' +
      '</select></div>' +
      '<div class="field"><label>' + esc(t('bh.transport')) + '</label><select id="b-transport">' + transports + '</select></div>' +
    '</div>' +
    '<div class="hint" style="margin:-6px 0 14px">' + esc(t('bh.roleHint')) + '</div>' +

    '<div class="field"><label>' + esc(t('bh.token')) + '</label>' +
      '<div style="display:flex;gap:8px">' +
        '<input id="b-token" class="mono" value="' + esc(data.token) + '">' +
        '<button type="button" class="btn btn-sm" id="b-gen-token">↻</button>' +
      '</div><div class="hint">' + esc(t('bh.tokenHint')) + '</div></div>' +

    '<fieldset id="b-server-fields"><legend>' + esc(t('bh.server')) + '</legend>' +
      '<div class="form-grid">' +
        '<div class="field"><label>' + esc(t('bh.bindAddr')) + '</label><input id="b-bind" class="mono" value="' + esc(data.bind_addr) + '"></div>' +
        '<div class="field"><label>' + esc(t('bh.heartbeat')) + '</label><input id="b-heartbeat" type="number" value="' + esc(data.heartbeat) + '"></div>' +
        '<div class="field"><label>' + esc(t('bh.channelSize')) + '</label><input id="b-channel" type="number" value="' + esc(data.channel_size) + '"></div>' +
      '</div>' +
      '<div class="check"><input type="checkbox" id="b-udp"' + (data.accept_udp ? ' checked' : '') + '>' +
        '<label for="b-udp">' + esc(t('bh.acceptUdp')) + '</label></div>' +
      '<label style="font-size:13px;color:var(--muted)">' + esc(t('bh.ports')) + '</label>' +
      '<div id="b-ports" style="margin-top:8px">' +
        (data.ports && data.ports.length ? data.ports.map(portRow).join('') : portRow('')) + '</div>' +
      '<button type="button" class="btn btn-sm" id="b-add-port">+ ' + esc(t('bh.addPort')) + '</button>' +
      '<div class="hint" style="margin-top:8px">' + esc(t('bh.portsHint')) + '</div>' +
    '</fieldset>' +

    '<fieldset id="b-client-fields" class="hidden"><legend>' + esc(t('bh.client')) + '</legend>' +
      '<div class="form-grid">' +
        '<div class="field"><label>' + esc(t('bh.remoteAddr')) + '</label><input id="b-remote" class="mono" value="' + esc(data.remote_addr) + '" placeholder="1.2.3.4:3080"></div>' +
        '<div class="field"><label>' + esc(t('bh.edgeIp')) + ' (' + esc(t('common.optional')) + ')</label><input id="b-edge" class="mono" value="' + esc(data.edge_ip) + '"></div>' +
        '<div class="field"><label>' + esc(t('bh.connectionPool')) + '</label><input id="b-pool" type="number" value="' + esc(data.connection_pool) + '"></div>' +
        '<div class="field"><label>' + esc(t('bh.dialTimeout')) + '</label><input id="b-dial" type="number" value="' + esc(data.dial_timeout) + '"></div>' +
        '<div class="field"><label>' + esc(t('bh.retryInterval')) + '</label><input id="b-retry" type="number" value="' + esc(data.retry_interval) + '"></div>' +
      '</div>' +
      '<div class="check"><input type="checkbox" id="b-aggressive"' + (data.aggressive_pool ? ' checked' : '') + '>' +
        '<label for="b-aggressive">' + esc(t('bh.aggressivePool')) + '</label></div>' +
    '</fieldset>' +

    '<fieldset id="b-mux-fields" class="hidden"><legend>' + esc(t('bh.mux')) + '</legend>' +
      '<div class="form-grid">' +
        '<div class="field"><label>mux_con</label><input id="b-muxcon" type="number" value="' + esc(data.mux_con) + '"></div>' +
        '<div class="field"><label>mux_version</label><input id="b-muxver" type="number" min="1" max="2" value="' + esc(data.mux_version) + '"></div>' +
        '<div class="field"><label>mux_framesize</label><input id="b-muxframe" type="number" value="' + esc(data.mux_framesize) + '"></div>' +
        '<div class="field"><label>mux_receivebuffer</label><input id="b-muxrecv" type="number" value="' + esc(data.mux_receivebuffer) + '"></div>' +
        '<div class="field"><label>mux_streambuffer</label><input id="b-muxstream" type="number" value="' + esc(data.mux_streambuffer) + '"></div>' +
      '</div>' +
    '</fieldset>' +

    '<fieldset id="b-tls-fields" class="hidden"><legend>' + esc(t('bh.tls')) + '</legend>' +
      '<div class="form-grid">' +
        '<div class="field"><label>' + esc(t('bh.tlsCert')) + '</label><input id="b-cert" class="mono" value="' + esc(data.tls_cert) + '" placeholder="/etc/ssl/certs/server.crt"></div>' +
        '<div class="field"><label>' + esc(t('bh.tlsKey')) + '</label><input id="b-key" class="mono" value="' + esc(data.tls_key) + '" placeholder="/etc/ssl/private/server.key"></div>' +
      '</div><div class="hint">' + esc(t('bh.tlsHint')) + '</div>' +
    '</fieldset>' +

    '<fieldset><legend>' + esc(t('ssh.advanced')) + '</legend>' +
      '<div class="form-grid">' +
        '<div class="field"><label>' + esc(t('bh.keepalive')) + '</label><input id="b-keepalive" type="number" value="' + esc(data.keepalive_period) + '"></div>' +
        '<div class="field"><label>' + esc(t('bh.webPort')) + '</label><input id="b-webport" type="number" value="' + esc(data.web_port) + '">' +
          '<div class="hint">' + esc(t('bh.webPortHint')) + '</div></div>' +
        '<div class="field"><label>' + esc(t('bh.logLevel')) + '</label><select id="b-loglevel">' + levels + '</select></div>' +
        '<div class="field"><label>' + esc(t('common.note')) + ' (' + esc(t('common.optional')) + ')</label><input id="b-note" value="' + esc(data.note || '') + '" maxlength="200"></div>' +
      '</div>' +
      '<div class="check"><input type="checkbox" id="b-nodelay"' + (data.nodelay ? ' checked' : '') + '>' +
        '<label for="b-nodelay">' + esc(t('bh.nodelay')) + '</label></div>' +
      '<div class="check"><input type="checkbox" id="b-sniffer"' + (data.sniffer ? ' checked' : '') + '>' +
        '<label for="b-sniffer">' + esc(t('bh.sniffer')) + '</label></div>' +
      (editing ? '' : '<div class="check"><input type="checkbox" id="b-autostart" checked>' +
        '<label for="b-autostart">' + esc(t('common.autostart')) + '</label></div>') +
    '</fieldset>' +
    '<div class="form-error" id="b-error"></div>';

  openModal(
    editing ? t('bh.edit') : t('bh.new'),
    body,
    (editing ? '<button class="btn" id="b-view-config">' + esc(t('bh.viewConfig')) + '</button>' : '') +
    '<div class="spacer"></div>' +
    '<button class="btn" data-close="1">' + esc(t('common.cancel')) + '</button>' +
    '<button class="btn btn-primary" id="b-save">' + esc(t('common.save')) + '</button>'
  );

  function syncRole() {
    const role = document.getElementById('b-role').value;
    const transport = document.getElementById('b-transport').value;
    document.getElementById('b-server-fields').classList.toggle('hidden', role !== 'server');
    document.getElementById('b-client-fields').classList.toggle('hidden', role !== 'client');
    document.getElementById('b-mux-fields').classList.toggle(
      'hidden', ['tcpmux', 'wsmux', 'wssmux'].indexOf(transport) === -1);
    document.getElementById('b-tls-fields').classList.toggle(
      'hidden', role !== 'server' || ['wss', 'wssmux'].indexOf(transport) === -1);
  }
  document.getElementById('b-role').addEventListener('change', syncRole);
  document.getElementById('b-transport').addEventListener('change', syncRole);
  syncRole();

  function bindPortRow(row) {
    row.querySelector('.rm').addEventListener('click', function () { row.remove(); });
  }
  document.querySelectorAll('#b-ports .port-row').forEach(bindPortRow);
  document.getElementById('b-add-port').addEventListener('click', function () {
    const holder = document.getElementById('b-ports');
    holder.insertAdjacentHTML('beforeend', portRow(''));
    bindPortRow(holder.lastElementChild);
  });

  document.getElementById('b-gen-token').addEventListener('click', async function () {
    try {
      const result = await api('/api/backhaul/token');
      document.getElementById('b-token').value = result.token;
    } catch (exc) { toast(exc.message, 'err'); }
  });

  if (editing) {
    document.getElementById('b-view-config').addEventListener('click', async function () {
      try {
        const text = await api('/api/backhaul/' + tunnel.id + '/config');
        openModal(t('bh.config') + ' — ' + tunnel.name,
          '<pre class="log">' + esc(text) + '</pre>',
          '<button class="btn btn-primary" data-close="1">' + esc(t('common.close')) + '</button>');
      } catch (exc) { toast(exc.message, 'err'); }
    });
  }

  function collect() {
    const ports = [];
    document.querySelectorAll('#b-ports .p-value').forEach(function (input) {
      const value = input.value.trim();
      if (value) ports.push(value);
    });
    return {
      name: document.getElementById('b-name').value.trim(),
      role: document.getElementById('b-role').value,
      transport: document.getElementById('b-transport').value,
      token: document.getElementById('b-token').value.trim(),
      bind_addr: document.getElementById('b-bind').value.trim(),
      heartbeat: document.getElementById('b-heartbeat').value,
      channel_size: document.getElementById('b-channel').value,
      accept_udp: document.getElementById('b-udp').checked,
      ports: ports,
      remote_addr: document.getElementById('b-remote').value.trim(),
      edge_ip: document.getElementById('b-edge').value.trim(),
      connection_pool: document.getElementById('b-pool').value,
      aggressive_pool: document.getElementById('b-aggressive').checked,
      dial_timeout: document.getElementById('b-dial').value,
      retry_interval: document.getElementById('b-retry').value,
      mux_con: document.getElementById('b-muxcon').value,
      mux_version: document.getElementById('b-muxver').value,
      mux_framesize: document.getElementById('b-muxframe').value,
      mux_receivebuffer: document.getElementById('b-muxrecv').value,
      mux_streambuffer: document.getElementById('b-muxstream').value,
      tls_cert: document.getElementById('b-cert').value.trim(),
      tls_key: document.getElementById('b-key').value.trim(),
      keepalive_period: document.getElementById('b-keepalive').value,
      web_port: document.getElementById('b-webport').value,
      log_level: document.getElementById('b-loglevel').value,
      nodelay: document.getElementById('b-nodelay').checked,
      sniffer: document.getElementById('b-sniffer').checked,
      note: document.getElementById('b-note').value,
      autostart: document.getElementById('b-autostart') ? document.getElementById('b-autostart').checked : false
    };
  }

  document.getElementById('b-save').addEventListener('click', async function () {
    const button = this;
    const error = document.getElementById('b-error');
    button.disabled = true;
    error.textContent = '';
    try {
      const payload = collect();
      if (editing) await api('/api/backhaul/' + tunnel.id, { method: 'PUT', body: payload });
      else await api('/api/backhaul', { method: 'POST', body: payload });
      closeModal();
      toast(t('msg.saved'), 'ok');
      render();
    } catch (exc) {
      error.textContent = exc.message;
      button.disabled = false;
    }
  });
}

/* ── keys view ──────────────────────────────────────────────────────── */

async function viewKeys() {
  const keys = await api('/api/keys');
  state.keys = keys;

  const cards = keys.map(function (key) {
    return '<div class="card">' +
      '<div class="card-head"><h3>⚿ ' + esc(key.name) + '</h3><div class="spacer"></div>' +
        '<button class="btn btn-sm" data-copy="' + esc(key.name) + '">' + esc(t('common.copy')) + '</button>' +
        '<button class="btn btn-sm btn-danger" data-delkey="' + key.id + '">' + esc(t('common.delete')) + '</button>' +
      '</div>' +
      '<div class="kv"><span>' + esc(t('keys.fingerprint')) + '</span><span class="mono">' + esc(key.fingerprint || '—') + '</span></div>' +
      '<div class="field" style="margin-top:12px"><label>' + esc(t('keys.publicKey')) + '</label>' +
        '<textarea readonly style="min-height:76px" id="pub-' + esc(key.name) + '">' + esc(key.public_key) + '</textarea>' +
        '<div class="hint">' + esc(t('keys.copyHint')) + '</div></div>' +
    '</div>';
  }).join('');

  document.getElementById('view').innerHTML =
    '<div class="card-head">' +
      '<button class="btn btn-primary" id="k-generate">+ ' + esc(t('keys.generate')) + '</button>' +
      '<button class="btn" id="k-import">↥ ' + esc(t('keys.import')) + '</button>' +
    '</div>' +
    (keys.length
      ? '<div class="grid grid-2">' + cards + '</div>'
      : '<div class="card empty"><span class="big">⚿</span>' + esc(t('keys.empty')) +
        '<div class="muted" style="margin-top:6px">' + esc(t('keys.emptyHint')) + '</div></div>');

  document.getElementById('k-generate').addEventListener('click', function () { keyForm(false); });
  document.getElementById('k-import').addEventListener('click', function () { keyForm(true); });

  document.querySelectorAll('[data-copy]').forEach(function (button) {
    button.addEventListener('click', function () {
      const area = document.getElementById('pub-' + button.dataset.copy);
      area.select();
      navigator.clipboard.writeText(area.value).then(function () {
        toast(t('common.copied'), 'ok');
      }).catch(function () { document.execCommand('copy'); });
    });
  });

  document.querySelectorAll('[data-delkey]').forEach(function (button) {
    button.addEventListener('click', function () {
      const key = keys.find(function (item) { return item.id === Number(button.dataset.delkey); });
      confirmDialog(key.name, async function () {
        try {
          await api('/api/keys/' + key.id, { method: 'DELETE' });
          toast(t('msg.deleted'), 'ok');
          render();
        } catch (exc) { toast(exc.message, 'err'); }
      });
    });
  });
}

function keyForm(isImport) {
  openModal(
    isImport ? t('keys.import') : t('keys.generate'),
    '<div class="field"><label>' + esc(t('keys.name')) + '</label>' +
      '<input id="k-name" placeholder="tokyo-key" maxlength="32"></div>' +
    (isImport
      ? '<div class="field"><label>' + esc(t('keys.privateKey')) + '</label>' +
        '<textarea id="k-private" style="min-height:180px" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea>' +
        '<div class="hint">' + esc(t('keys.privateHint')) + '</div></div>'
      : '') +
    '<div class="form-error" id="k-error"></div>',
    '<button class="btn" data-close="1">' + esc(t('common.cancel')) + '</button>' +
    '<button class="btn btn-primary" id="k-save">' + esc(t('common.save')) + '</button>'
  );

  document.getElementById('k-save').addEventListener('click', async function () {
    const button = this;
    const error = document.getElementById('k-error');
    button.disabled = true;
    error.textContent = '';
    try {
      const body = { name: document.getElementById('k-name').value.trim() };
      if (isImport) body.private_key = document.getElementById('k-private').value;
      await api('/api/keys', { method: 'POST', body: body });
      closeModal();
      toast(t('msg.saved'), 'ok');
      render();
    } catch (exc) {
      error.textContent = exc.message;
      button.disabled = false;
    }
  });
}

/* ── settings view ──────────────────────────────────────────────────── */

async function viewSettings() {
  const [settings, me] = await Promise.all([api('/api/settings'), api('/api/me')]);

  document.getElementById('view').innerHTML =
    '<div class="grid grid-2">' +
      '<div class="card">' +
        '<div class="card-head"><h3>' + esc(t('set.panel')) + '</h3></div>' +
        '<div class="field"><label>' + esc(t('set.port')) + '</label>' +
          '<input id="s-port" type="number" value="' + esc(settings.port) + '"></div>' +
        '<div class="field"><label>' + esc(t('set.language')) + '</label><select id="s-lang">' +
          '<option value="fa"' + (settings.language === 'fa' ? ' selected' : '') + '>فارسی</option>' +
          '<option value="en"' + (settings.language === 'en' ? ' selected' : '') + '>English</option>' +
        '</select></div>' +
        '<div class="field"><label>' + esc(t('set.sessionHours')) + '</label>' +
          '<input id="s-hours" type="number" min="1" max="720" value="' + esc(settings.session_hours) + '"></div>' +
        '<div class="hint" style="margin-bottom:12px">' + esc(t('set.restartHint')) + '</div>' +
        '<div style="display:flex;gap:10px">' +
          '<button class="btn btn-primary" id="s-save">' + esc(t('common.save')) + '</button>' +
          '<button class="btn" id="s-restart">' + esc(t('set.restart')) + '</button>' +
        '</div>' +
        '<div class="form-error" id="s-error"></div>' +
      '</div>' +

      '<div class="card">' +
        '<div class="card-head"><h3>' + esc(t('set.account')) + '</h3></div>' +
        '<div class="field"><label>' + esc(t('set.currentPassword')) + '</label>' +
          '<input id="a-current" type="password" autocomplete="current-password"></div>' +
        '<div class="field"><label>' + esc(t('set.newUsername')) + '</label>' +
          '<input id="a-username" value="' + esc(me.username) + '"></div>' +
        '<div class="field"><label>' + esc(t('set.newPassword')) + '</label>' +
          '<input id="a-password" type="password" autocomplete="new-password">' +
          '<div class="hint">' + esc(t('set.newPasswordHint')) + '</div></div>' +
        '<button class="btn btn-primary" id="a-save">' + esc(t('common.save')) + '</button>' +
        '<div class="form-error" id="a-error"></div>' +
      '</div>' +
    '</div>' +

    '<div class="card" style="margin-top:16px">' +
      '<div class="card-head"><h3>' + esc(t('set.about')) + '</h3></div>' +
      kv('Eris Tunnel', 'v' + me.version) +
      kv('GitHub', 'github.com/eris4444/eris-tunnel') +
      kv('Backhaul', (state.system && state.system.panel.backhaul) || '—') +
    '</div>';

  document.getElementById('s-save').addEventListener('click', async function () {
    const error = document.getElementById('s-error');
    error.textContent = '';
    try {
      const result = await api('/api/settings', {
        method: 'POST',
        body: {
          port: document.getElementById('s-port').value,
          language: document.getElementById('s-lang').value,
          session_hours: document.getElementById('s-hours').value
        }
      });
      toast(t('msg.saved'), 'ok');
      if (result.restart_needed) error.textContent = t('set.restartHint');
    } catch (exc) { error.textContent = exc.message; }
  });

  document.getElementById('s-restart').addEventListener('click', async function () {
    try {
      await api('/api/panel/restart', { method: 'POST' });
      toast(t('set.restarting'), 'ok');
    } catch (exc) { toast(exc.message, 'err'); }
  });

  document.getElementById('a-save').addEventListener('click', async function () {
    const error = document.getElementById('a-error');
    error.textContent = '';
    try {
      const result = await api('/api/account', {
        method: 'POST',
        body: {
          current_password: document.getElementById('a-current').value,
          username: document.getElementById('a-username').value,
          new_password: document.getElementById('a-password').value
        }
      });
      state.token = result.token;
      localStorage.setItem('eris_token', result.token);
      toast(t('set.accountSaved'), 'ok');
      document.getElementById('a-current').value = '';
      document.getElementById('a-password').value = '';
    } catch (exc) { error.textContent = exc.message; }
  });
}

/* ── boot ───────────────────────────────────────────────────────────── */

(async function boot() {
  setLang(LANG);
  document.getElementById('login-lang').textContent = LANG === 'fa' ? 'English' : 'فارسی';
  if (!state.token) return;
  try {
    await startPanel();
  } catch (exc) {
    logout(true);
  }
})();
