(function () {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = value => value && Number.isFinite(Date.parse(value)) ? new Date(value) : null;
  const dateLabel = value => date(value)?.toLocaleDateString('ko-KR', {timeZone:'Asia/Seoul',year:'numeric',month:'long',day:'numeric'}) || '완성일 미기록';
  const monthLabel = value => date(value)?.toLocaleDateString('ko-KR', {timeZone:'Asia/Seoul',year:'numeric',month:'long'}) || '완성일 미기록';
  let posts = [], view = null, trigger = null;
  const modal = $('#archive-modal');
  function applyTheme(theme) {
    if (theme) document.documentElement.dataset.theme = theme;
    const dark = theme === 'dark' || (!theme && matchMedia('(prefers-color-scheme: dark)').matches);
    $('#theme-toggle').textContent = dark ? '☀️' : '🌙';
  }
  try { applyTheme(JSON.parse(localStorage.getItem('hp-theme'))); } catch (_) { applyTheme(''); }
  $('#theme-toggle').addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme === 'dark' || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    applyTheme(next); try { localStorage.setItem('hp-theme', JSON.stringify(next)); } catch (_) { /* Theme still works for this page. */ }
  });
  function render() {
    const query = $('#archive-query').value.trim().toLocaleLowerCase();
    const list = posts.filter(post => [post.title, post.username, post.shortcode].join(' ').toLocaleLowerCase().includes(query))
      .sort((a,b) => {
        const left = date(a.completed_at), right = date(b.completed_at);
        if (!left || !right) return Number(!left) - Number(!right) || a.shortcode.localeCompare(b.shortcode);
        return (right - left || a.shortcode.localeCompare(b.shortcode)) * ($('#archive-sort').value === 'oldest' ? -1 : 1);
      });
    $('#archive-count').textContent = posts.length;
    $('#archive-result').textContent = query ? `전체 ${posts.length}개 중 검색 결과 ${list.length}개` : `완성한 게시물 ${posts.length}개 · 표지를 누르면 영상과 게시물 문구를 확인할 수 있어요.`;
    $('#archive-empty').hidden = list.length > 0;
    $('#archive-empty').textContent = query ? '검색 결과가 없어요. 다른 문구나 계정으로 검색해 보세요.' : '아직 완성한 게시물이 없어요. 제작을 마친 게시물은 여기에 쌓입니다.';
    const groups = new Map();
    for (const post of list) { const key = monthLabel(post.completed_at); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(post); }
    $('#archive-list').innerHTML = Array.from(groups, ([month, items]) => `<section aria-label="${esc(month)} 완성기록"><h3 class="archive-month">${esc(month)}<span>${items.length}개</span></h3><div class="archive-grid">${items.map(card).join('')}</div></section>`).join('');
    $('#archive-list').querySelectorAll('img').forEach(img => img.addEventListener('error', () => { img.hidden = true; img.nextElementSibling.hidden = false; }));
  }
  function card(post) {
    const title = post.title || `${post.username ? '@'+post.username : post.shortcode}의 완성 영상`;
    const image = post.media.cover || `thumbs/${encodeURIComponent(post.shortcode)}.jpg`;
    return `<article class="archive-card" data-code="${esc(post.shortcode)}">
      <button class="archive-poster" type="button" data-open="${esc(post.shortcode)}" aria-label="${esc(title.replace(/\n/g,' '))} 영상 보기">
        <img loading="lazy" src="${esc(image)}" alt="${esc(title.replace(/\n/g,' '))} ${post.media.cover ? '표지' : '레퍼런스 썸네일'}">
        <span class="archive-placeholder" hidden><svg viewBox="0 0 48 48" aria-hidden="true"><rect x="7" y="5" width="34" height="38" rx="5"/><path d="m20 17 12 7-12 7z"/></svg>표지 이미지 없음</span>
        ${!post.media.cover ? '<span class="archive-reference-label">레퍼런스 썸네일</span>' : ''}
        ${post.media.final ? '<span class="archive-play" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m7 4 14 8-14 8z"/></svg></span>' : ''}
      </button><div class="archive-card-body"><div class="archive-card-meta"><span class="archive-complete">제작 완료</span><time datetime="${esc(post.completed_at || '')}">${esc(dateLabel(post.completed_at))}</time></div>
      <h3>${esc(title)}</h3><p class="archive-account">${esc(post.username ? '@'+post.username : post.shortcode)}</p>
      ${!post.media.final ? '<p class="archive-unavailable">이 PC의 완성 영상 파일을 확인할 수 없어요.</p>' : ''}
      <button class="btn ghost archive-open" type="button" data-open="${esc(post.shortcode)}">${post.media.final ? '영상 · 게시물 준비' : '게시물 기록 확인'} <span aria-hidden="true">→</span></button></div></article>`;
  }
  function close() {
    if (modal.hidden) return;
    view?.close(); view = null;
    modal.querySelectorAll('video,audio').forEach(player => player.pause());
    $('#archive-detail').textContent = '';
    modal.hidden = true; document.body.style.overflow = '';
    trigger?.focus();
  }
  $('#archive-list').addEventListener('click', event => {
    const button = event.target.closest('[data-open]'); if (!button) return;
    const post = posts.find(item => item.shortcode === button.dataset.open); if (!post) return;
    trigger = button; view?.close();
    modal.hidden = false; document.body.style.overflow = 'hidden';
    view = window.PostPreparation.mount($('#archive-detail'), post);
    modal.querySelector('[data-close][aria-label]').focus();
  });
  modal.addEventListener('click', event => { if (event.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', event => {
    if (modal.hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key !== 'Tab') return;
    const items = Array.from(modal.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),video[controls]')).filter(el => el.getClientRects().length);
    const first = items[0], last = items[items.length-1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  async function load() {
    $('#archive-retry').hidden = true; $('#archive-empty').hidden = true;
    $('#archive-result').textContent = '완성기록을 불러오는 중…';
    try {
      const response = await fetch('/api/completed-posts', {cache:'no-store'});
      if (!response.ok) throw new Error();
      const result = await response.json(); if (!Array.isArray(result.posts)) throw new Error();
      posts = result.posts; render();
    } catch (_) { $('#archive-result').textContent = '완성기록을 불러오지 못했어요. 서버 연결을 확인하고 다시 시도해 주세요.'; $('#archive-retry').hidden = false; }
  }
  $('#archive-query').addEventListener('input', render);
  $('#archive-sort').addEventListener('change', render);
  $('#archive-retry').addEventListener('click', load);
  load();
})();
