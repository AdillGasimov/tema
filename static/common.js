export const $ = id => document.getElementById(id);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const fmt = cents => (cents / 100).toFixed(2) + ' AZN';
export async function api(path, {method='GET', body, csrf, form}={}) {
  const headers = {};
  if (csrf) headers['X-CSRF-Token'] = csrf;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method, headers, credentials:'same-origin', cache:'no-store', body:form ?? (body === undefined ? undefined : JSON.stringify(body))});
  let result;
  try { result = await response.json(); } catch { throw new Error('Server cavabı alınmadı. Yenidən yoxlayın.'); }
  if (!response.ok) {
    const error = new Error(result.error || 'Əməliyyat alınmadı.');
    error.status = response.status;
    throw error;
  }
  return result;
}
