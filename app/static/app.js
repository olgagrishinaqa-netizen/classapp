const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let me = null;
const columns = {created: 'Общий список', in_progress: 'В работе', done: 'Выполнено'};

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get('content-type') || '';
  const raw = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof raw === 'string' ? raw : raw?.error || 'Произошла ошибка';
    throw new Error(message);
  }
  return raw;
}
function toast(message) { const node = $('#toast'); node.textContent = message; node.classList.add('show'); setTimeout(() => node.classList.remove('show'), 2600); }
function formData(form) { return Object.fromEntries(new FormData(form)); }
function showPage(page) {
  $$('.page').forEach(node => node.classList.toggle('hidden', node.id !== `${page}-page`));
  $$('#nav button').forEach(node => node.classList.toggle('active', node.dataset.page === page));
  $('#page-title').textContent = {dashboard:'Добро пожаловать', tasks:'Задачи класса', news:'Новости', users:'Пользователи', reports:'Отчетность'}[page];
  if (page === 'dashboard' || page === 'tasks') loadTasks();
  if (page === 'news') loadNews();
  if (page === 'users') loadUsers();
  if (page === 'reports') loadReports();
}
function renderKanban(tasks, target) {
  $(target).innerHTML = Object.entries(columns).map(([status, label]) => {
    const list = tasks.filter(task => task.status === status);
    return `<div class="kanban-column"><div class="column-head"><span>${label}</span><span class="count">${list.length}</span></div>${list.length ? list.map(task => `<article class="task-card"><b>${escapeHtml(task.title)}</b><p>${escapeHtml(task.description)}</p><time>${task.created_at}${me?.active_role === 'admin' ? ` · <select class="status-select" data-id="${task.id}"><option value="created" ${status==='created'?'selected':''}>Создана</option><option value="in_progress" ${status==='in_progress'?'selected':''}>В работе</option><option value="done" ${status==='done'?'selected':''}>Сделано</option></select>` : ''}</time></article>`).join('') : '<p class="muted">Пока пусто</p>'}</div>`;
  }).join('');
  $$('.status-select').forEach(select => select.addEventListener('change', async event => { try { await api(`/api/tasks/${event.target.dataset.id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:event.target.value})}); toast('Статус задачи обновлен'); loadTasks(); } catch(error) { toast(error.message); } }));
}
async function loadTasks() { try { const data = await api('/api/tasks'); renderKanban(data.tasks, '#tasks-kanban'); renderKanban(data.tasks, '#dashboard-kanban'); } catch(error) { toast(error.message); } }
async function loadUsers() { try { const data = await api('/api/users'); $('#users-list').innerHTML = data.users.map(user => `<div class="user-row"><div><b>${escapeHtml(user.full_name)}</b><small>${escapeHtml(user.phone)}</small></div><span class="role-pill">${user.role_label}</span><button class="ghost edit-user" data-id="${user.id}" data-name="${escapeHtml(user.full_name)}" data-phone="${escapeHtml(user.phone)}" data-role="${user.role}">Изменить</button></div>`).join(''); $$('.edit-user').forEach(button => button.addEventListener('click', async () => { const full_name = prompt('ФИО', button.dataset.name); const phone = prompt('Телефон', button.dataset.phone); const role = prompt('Роль: parent или student', button.dataset.role); if (!full_name || !phone || !['parent','student'].includes(role)) return; try { await api(`/api/users/${button.dataset.id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({full_name, phone, role})}); toast('Данные пользователя обновлены'); loadUsers(); } catch(error) { toast(error.message); } })); } catch(error) { toast(error.message); } }
function expenseRow() { const row = document.createElement('div'); row.className = 'expense-row'; row.innerHTML = '<div class="form-grid"><input class="expense-title" placeholder="Статья расхода"><input class="expense-amount" type="number" min="0" step="0.01" placeholder="Сумма, ₽"></div>'; $('#expense-items').append(row); }
async function loadReports() { try { const data = await api('/api/reports'); const totalIncome = data.reports.reduce((sum, report) => sum + report.income, 0); const totalExpenses = data.reports.reduce((sum, report) => sum + report.total_expenses, 0); $('#report-summary').innerHTML = `<p class="eyebrow">ОБЩИЙ ОСТАТОК</p><div class="amount">${money(totalIncome-totalExpenses)}</div><small>Поступления ${money(totalIncome)} · Расходы ${money(totalExpenses)}</small>`; $('#reports-list').innerHTML = data.reports.map(report => `<div class="report-item"><div><b>${money(report.income)} поступление</b><small>${report.items.map(item => `${escapeHtml(item.title)}: ${money(item.amount)}`).join(' · ') || 'Без расходов'}</small></div><strong class="${report.balance >= 0 ? 'positive':'negative'}">${money(report.balance)}</strong></div>`).join('') || '<p class="muted">Отчетов пока нет.</p>'; } catch(error) { toast(error.message); } }

async function loadNews() {
  try {
    const data = await api('/api/news');
    const admin = me?.active_role === 'admin';
    const filter = admin ? ($('#news-filter').value || 'all') : 'published';
    const news = (data.news || []).filter(item => filter === 'all' || item.status === filter);
    $('#news-list').innerHTML = news.length ? news.map(item => `
      <article class="news-item">
        <div class="news-media">
          ${item.image_url ? `<img src="${item.image_url}" alt="${escapeHtml(item.title)}" class="news-image">` : '<div class="news-placeholder"><span>✦</span><small>КЛАСС · НОВОСТИ</small></div>'}
        </div>
        <div class="news-body">
          <div class="news-head">
            <h4>${escapeHtml(item.title)}</h4>
            <span class="news-status ${item.status === 'published' ? 'published' : 'draft'}">${item.status === 'published' ? 'Опубликовано' : 'Черновик'}</span>
          </div>
          <p>${escapeHtml(item.description)}</p>
          <small>${item.created_at}</small>
          ${admin ? `
            <div class="news-actions">
              <button class="ghost edit-news" data-id="${item.id}" data-title="${escapeHtml(item.title)}" data-description="${escapeHtml(item.description)}" data-status="${item.status}">Редактировать</button>
              <button class="primary toggle-news-status" data-id="${item.id}" data-status="${item.status === 'published' ? 'draft' : 'published'}">${item.status === 'published' ? 'Вернуть в черновик' : 'Опубликовать'}</button>
            </div>
          ` : ''}
        </div>
      </article>
    `).join('') : '<p class="muted">Новостей пока нет.</p>';

    if (admin) {
      $$('.edit-news').forEach(button => button.addEventListener('click', () => {
        $('#news-edit-id').value = button.dataset.id;
        $('#news-title').value = button.dataset.title;
        $('#news-description').value = button.dataset.description;
        $('#news-status').value = button.dataset.status;
        $('#news-form').classList.remove('hidden');
      }));
      $$('.toggle-news-status').forEach(button => button.addEventListener('click', async () => {
        try {
          await api(`/api/news/${button.dataset.id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status: button.dataset.status})});
          toast('Статус новости обновлен');
          loadNews();
        } catch(error) {
          toast(error.message);
        }
      }));
    }
  } catch(error) {
    toast(error.message);
  }
}

function money(value) { return `${Number(value).toLocaleString('ru-RU', {minimumFractionDigits:2, maximumFractionDigits:2})} ₽`; }
function escapeHtml(value) { return String(value || '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }
function setUser(user, activeRole) { me = {user, active_role: activeRole}; $('#user-name').textContent = user.full_name; $('#user-role').textContent = activeRole === 'admin' ? 'Админ' : 'Родитель'; $('#avatar').textContent = user.full_name[0]; $('#role-switch').value = activeRole; $$('.admin-only').forEach(node => node.classList.toggle('hidden', activeRole !== 'admin')); }
async function enter() { const data = await api('/api/me'); if (!data.user) return; setUser(data.user, data.active_role); $('#login-view').classList.add('hidden'); $('#app-view').classList.remove('hidden'); showPage('dashboard'); }
$('#login-form').addEventListener('submit', async event => { event.preventDefault(); try { const data = await api('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(formData(event.target))}); setUser(data.user, data.active_role); $('#login-view').classList.add('hidden'); $('#app-view').classList.remove('hidden'); showPage('dashboard'); } catch(error) { $('#login-error').textContent = error.message; } });
$('#logout').addEventListener('click', async () => { await api('/api/logout', {method:'POST'}); location.reload(); });
$$('[data-page]').forEach(button => button.addEventListener('click', () => showPage(button.dataset.page)));
$('#role-switch').addEventListener('change', async event => { try { const data = await api('/api/role', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({role:event.target.value})}); setUser(me.user, data.active_role); showPage(data.active_role === 'admin' ? 'reports' : 'dashboard'); } catch(error) { toast(error.message); } });
$('#new-task').addEventListener('click', () => $('#task-form').classList.remove('hidden')); $('#cancel-task').addEventListener('click', () => $('#task-form').classList.add('hidden')); $('#save-task').addEventListener('click', async () => { try { await api('/api/tasks', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:$('#task-title').value, description:$('#task-description').value})}); $('#task-title').value=''; $('#task-description').value=''; $('#task-form').classList.add('hidden'); toast('Задача создана'); loadTasks(); } catch(error) { toast(error.message); } });
$('#new-news').addEventListener('click', () => { $('#news-edit-id').value=''; $('#news-title').value=''; $('#news-description').value=''; $('#news-status').value='draft'; $('#news-image').value=''; $('#news-form').classList.remove('hidden'); }); $('#cancel-news').addEventListener('click', () => $('#news-form').classList.add('hidden')); $('#save-news').addEventListener('click', async () => { const id = $('#news-edit-id').value; const data = new FormData(); data.append('title', $('#news-title').value); data.append('description', $('#news-description').value); data.append('status', $('#news-status').value); if ($('#news-image').files[0]) data.append('image', $('#news-image').files[0]); try { await api(id ? `/api/news/${id}` : '/api/news', {method:id ? 'PATCH' : 'POST', body:data}); $('#news-form').classList.add('hidden'); $('#news-title').value=''; $('#news-description').value=''; $('#news-status').value='draft'; $('#news-image').value=''; $('#news-edit-id').value=''; toast(id ? 'Новость обновлена' : 'Новость создана'); loadNews(); } catch(error) { toast(error.message); } });
$('#news-filter').addEventListener('change', loadNews);
$('#new-user').addEventListener('click', () => $('#user-form').classList.toggle('hidden'));
$('#save-user').addEventListener('click', async () => {
  const form = $('#user-form');
  const data = new FormData(form);
  const values = Object.fromEntries([...data.entries()].map(([key, value]) => [key, String(value).trim()]));

  if (!values.full_name || !values.phone || !values.role || !values.password) {
    toast('Заполните все обязательные поля');
    return;
  }

  try {
    await api('/api/users', {method:'POST', body:data});
    form.reset();
    form.classList.add('hidden');
    toast('Пользователь добавлен');
    loadUsers();
  } catch (error) {
    toast(error.message);
  }
});
$('#add-expense').addEventListener('click', expenseRow); expenseRow(); $('#save-report').addEventListener('click', async () => { const items = $$('.expense-row').map(row => ({title:row.querySelector('.expense-title').value, amount:row.querySelector('.expense-amount').value})).filter(item => item.title || item.amount); const data = new FormData(); data.append('income', $('#income').value || '0'); data.append('items', JSON.stringify(items)); if ($('#receipt').files[0]) data.append('receipt', $('#receipt').files[0]); try { await api('/api/reports', {method:'POST', body:data}); toast('Отчет сохранен'); $('#income').value=''; $('#expense-items').innerHTML=''; expenseRow(); loadReports(); } catch(error) { toast(error.message); } });
$('#date-label').textContent = new Date().toLocaleDateString('ru-RU', {weekday:'long', day:'numeric', month:'long'}).toUpperCase(); enter();
