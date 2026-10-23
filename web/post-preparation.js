(function () {
  'use strict';
  const labels = {recommended:'기본 제작 문구', hook:'후킹 강한 문구', curiosity:'궁금증을 부르는 문구', benefit:'사용했을 때의 이득'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function mount(root, post) {
    let closed = false, data, draftCache, timer, saving = false, pendingSave, version = 0, savedVersion = 0, conflict = false;
    let thumbnailTimer, applying = false;
    const controller = new AbortController(), endpoint = '/api/post-preparations/' + encodeURIComponent(post.shortcode);
    root.innerHTML = '<div class="prep-loading" role="status">게시물 준비 화면을 불러오는 중…</div>';
    const status = (message, error = false) => {
      const el = root.querySelector('[data-save-status]');
      if (el && !closed) { el.textContent = message; el.classList.toggle('is-error', error); }
    };
    function read() {
      return {
        selected_accounts: Array.from(root.querySelectorAll('[name="prep-account"]:checked'), e => e.value),
        thumbnail_options: Object.fromEntries(Object.keys(labels).map(key => [key, root.querySelector('[data-copy="'+key+'"]').value])),
        selected_thumbnail: root.querySelector('[name="prep-thumbnail"]:checked').value,
        caption: root.querySelector('[name="prep-caption"]').value,
        pinned_comment: root.querySelector('[name="prep-comment"]').value,
        dm_message: root.querySelector('[name="prep-dm"]').value,
        dm_button_text: root.querySelector('[name="prep-dm-button"]').value,
        product_link: root.querySelector('[name="prep-link"]').value
      };
    }
    async function save(force = false) {
      clearTimeout(timer);
      if (saving) return pendingSave;
      if (!data || conflict) return false;
      if (!force && version === savedVersion) return true;
      saving = true;
      const snapshot = version, draft = draftCache;
      status('저장 중…');
      pendingSave = (async () => { try {
        const response = await fetch(endpoint, {method:'PUT', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({revision:data.revision, draft}), keepalive:true});
        const result = await response.json();
        if (!response.ok) { if (response.status === 409) conflict = true; throw new Error(result.error || '저장하지 못했어요. 다시 저장해 주세요.'); }
        data.revision = result.revision; savedVersion = snapshot;
        status(version === snapshot ? '초안 저장됨' : '변경사항 저장 중…');
        return true;
      } catch (error) { status(error.message, true); return false; }
      finally { saving = false; if (!conflict && savedVersion === snapshot && version > snapshot) save(); }
      })();
      return pendingSave;
    }
    function changed() {
      version++;
      draftCache = read();
      root.querySelectorAll('.prep-option').forEach(el => el.classList.toggle('is-selected', el.querySelector('input').checked));
      const caption = root.querySelector('[name="prep-caption"]');
      root.querySelector('[data-caption-count]').textContent = caption.value.length + ' / 2,200';
      root.querySelector('[data-dm-button-count]').textContent = Array.from(draftCache.dm_button_text).length + ' / 20';
      status(conflict ? '다른 화면에서 변경됐어요. 입력을 복사한 뒤 다시 열어 주세요.' : '저장 전 변경사항', conflict);
      clearTimeout(timer); if (!conflict) timer = setTimeout(save, 700);
      thumbnailFeedback();
    }
    const busy = () => applying || ['queued','running'].includes(data?.thumbnail?.status);
    const downloadUrl = url => url + (url.includes('?')?'&':'?') + 'download=1';
    function thumbnailFeedback() {
      if (closed || !data) return;
      const button = root.querySelector('[data-apply-thumbnail]'), notice = root.querySelector('[data-thumbnail-status]');
      if (!button || !notice) return;
      const state = data.thumbnail || {}, text = draftCache.thumbnail_options[draftCache.selected_thumbnail].trim();
      const unchanged = text === (state.applied_text || '').trim();
      button.disabled = busy() || !state.ready || !text;
      button.textContent = busy() ? '썸네일 반영 중…' : '이 문구로 썸네일 반영';
      notice.classList.toggle('is-running',busy()); notice.classList.toggle('is-error',state.status==='failed');
      notice.setAttribute('aria-busy',String(busy()));
      notice.textContent = applying ? '초안을 저장하고 새 썸네일 생성을 시작하고 있어요…' :
        ['queued','running','failed'].includes(state.status) ? state.message :
        unchanged ? (state.status==='completed' ? '반영 완료! 현재 영상에 이 문구가 적용돼 있어요.' : '현재 영상에 적용된 문구예요.') :
        !state.ready ? '완성 영상과 원본 썸네일 배경이 준비되면 반영할 수 있어요.' :
        state.status==='completed' ? '직전 문구 반영은 완료됐어요. 현재 선택한 문구는 버튼을 눌러 다시 반영해 주세요.' :
        '변경한 문구는 아직 영상에 반영되지 않았어요. 버튼을 눌러 반영해 주세요.';
    }
    async function pollThumbnail() {
      clearTimeout(thumbnailTimer);
      if (closed) return;
      try {
        const response = await fetch(endpoint,{signal:controller.signal,cache:'no-store'});
        if (!response.ok) throw new Error('status');
        const fresh = await response.json();
        if (closed) return;
        data.thumbnail = fresh.thumbnail;
        if (fresh.thumbnail?.status==='completed' && fresh.media.final !== data.media.final) {
          const player = root.querySelector('.prep-media video');
          if (player) { player.pause(); player.setAttribute('poster',fresh.media.cover); player.setAttribute('src',fresh.media.final); player.load(); }
          const download = root.querySelector('.prep-download');
          if (download) download.setAttribute('href',downloadUrl(fresh.media.final));
          data.media = fresh.media;
        }
        thumbnailFeedback();
        if (['queued','running'].includes(data.thumbnail?.status)) thumbnailTimer = setTimeout(pollThumbnail,1200);
      } catch (_) {
        if (!closed) { const notice=root.querySelector('[data-thumbnail-status]');notice.textContent='연결을 다시 확인하고 있어요. 썸네일 작업 상태를 곧 다시 불러옵니다.';thumbnailTimer=setTimeout(pollThumbnail,2500); }
      }
    }
    async function applyThumbnail() {
      if (busy()) return;
      applying = true; thumbnailFeedback();
      try {
        let okay = await save();
        if (okay && savedVersion !== version) okay = await save();
        if (!okay || savedVersion !== version) throw new Error('초안 저장을 확인한 뒤 다시 반영해 주세요.');
        const response = await fetch(endpoint+'/thumbnail',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:data.revision})});
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '썸네일 반영을 시작하지 못했어요.');
        data.thumbnail = {...data.thumbnail,...result};
        applying=false;thumbnailFeedback();pollThumbnail();
      } catch (error) { applying=false;data.thumbnail={...data.thumbnail,status:'failed',message:error.message};thumbnailFeedback(); }
    }
    async function copyText(button) {
      const section = button.closest('.prep-section, .prep-option');
      const field = section.querySelector('textarea, input[type="text"]');
      const notice = section.querySelector('[data-copy-status]');
      button.disabled = true;
      try {
        await navigator.clipboard.writeText(field.value);
        if (!closed) { notice.textContent = '복사했어요.'; notice.classList.remove('is-error'); }
      } catch (_) {
        if (!closed) {
          field.focus(); field.select();
          notice.textContent = '복사 권한을 확인하거나 선택된 내용을 직접 복사해 주세요.';
          notice.classList.add('is-error');
        }
      } finally { button.disabled = false; }
    }
    function render() {
      const d = data.draft, media = data.media;
      const copyControl = label => `<div class="prep-copy-actions"><span data-copy-status role="status" aria-live="polite"></span><button class="prep-copy-button" type="button" data-copy-text aria-label="${esc(label)} 복사">복사</button></div>`;
      const player = (key, title) => `<section class="prep-media"><h3>${title}</h3>${media[key]
        ? `<video controls playsinline preload="metadata" ${key==='final' && media.cover ? `poster="${esc(media.cover)}"` : ''} src="${esc(media[key])}"></video>${key==='final' ? `<a class="prep-download" href="${esc(downloadUrl(media[key]))}" download>완성 영상 다운로드 ↓</a>` : ''}`
        : `<div class="prep-media-empty">${key==='final' ? '완성 영상이 아직 없어요.' : '저장된 레퍼런스 영상이 없어요.'}</div>`}</section>`;
      root.innerHTML = `<div class="post-preparation">
        <header class="prep-header"><span class="prep-eyebrow">POST PREPARATION</span><h2 id="prep-title">게시물 준비</h2><p>영상 확인부터 문구 선택까지 한곳에서 준비하세요.</p></header>
        <div class="prep-layout"><aside class="prep-preview">${player('final','완성 영상')}${player('reference','레퍼런스 영상')}</aside>
        <form class="prep-form">
          <fieldset class="prep-section"><legend><span>01</span> 업로드할 계정</legend><p class="prep-help">여러 계정을 함께 선택할 수 있어요.</p><div class="prep-accounts">${data.accounts.map(account=>`<label><input type="checkbox" name="prep-account" value="${esc(account)}" ${d.selected_accounts.includes(account)?'checked':''}><span>@${esc(account)}</span></label>`).join('')}</div></fieldset>
          <fieldset class="prep-section"><legend><span>02</span> 썸네일 문구</legend><p class="prep-help">문구를 고치고 아래 버튼을 누르면 현재 썸네일과 완성 영상의 첫 화면에 반영돼요.</p><div class="prep-options">${Object.keys(labels).map((key,i)=>`<div class="prep-option ${d.selected_thumbnail===key?'is-selected':''}"><label for="prep-choice-${key}"><input id="prep-choice-${key}" type="radio" name="prep-thumbnail" value="${key}" ${d.selected_thumbnail===key?'checked':''}><span>${labels[key]}</span>${i===0?'<b>추천</b>':''}</label><textarea data-copy="${key}" aria-label="${labels[key]}" maxlength="120" rows="2" placeholder="썸네일 문구를 입력하세요">${esc(d.thumbnail_options[key])}</textarea></div>`).join('')}</div><div class="prep-thumbnail-actions"><button type="button" data-apply-thumbnail>이 문구로 썸네일 반영</button><p>현재 완성 영상을 교체해요. 우상단 [광고]를 표시하고 음성은 그대로 유지해요.</p><div data-thumbnail-status role="status" aria-live="polite"></div></div></fieldset>
          <section class="prep-section"><h3><span>03</span> 인스타 게시물 내용</h3><p class="prep-help">${d.caption?'생활 속 활용과 장점을 자세히 담았어요. 마지막에는 관련 해시태그 5개가 있어요.':'저장된 제작 대본이 없어 비워뒀어요. 직접 입력할 수 있어요.'}</p><textarea name="prep-caption" aria-label="인스타 게시물 내용" maxlength="2200" rows="12" placeholder="게시물 내용을 입력하세요">${esc(d.caption)}</textarea><small class="prep-count" data-caption-count>${d.caption.length} / 2,200</small></section>
          <section class="prep-section"><h3><span>04</span> 고정댓글</h3><p class="prep-help">장점 한 줄 + 댓글 안내 한 줄로 준비했어요.</p><textarea name="prep-comment" aria-label="고정댓글" maxlength="2200" rows="3" placeholder="✨ 장점 한 줄&#10;💬 댓글에 &quot;나도&quot; 남겨주세요.">${esc(d.pinned_comment)}</textarea></section>
          <section class="prep-section"><h3><span>05</span> 쿠팡 인플루언서 제품 링크</h3><p class="prep-help">링크를 적어둘 수 있는 공간이에요. 연결 기능은 추후 추가해요.</p><input name="prep-link" type="text" inputmode="url" aria-label="쿠팡 인플루언서 제품 링크" maxlength="2048" placeholder="제품 링크를 입력하세요" value="${esc(d.product_link)}"></section>
          <section class="prep-section"><h3><span>06</span> DM으로 보낼 메시지</h3><p class="prep-help">모든 게시물에 공통으로 사용하는 고정 안내 문구예요.</p><textarea name="prep-dm" aria-label="DM으로 보낼 메시지" rows="5" readonly>${esc(d.dm_message)}</textarea></section>
          <section class="prep-section"><h3><span>07</span> DM 버튼 문구</h3><p class="prep-help">주제를 후킹하는 20자 이내 한 줄이에요. 원하는 문구로 수정할 수 있어요.</p><input name="prep-dm-button" type="text" aria-label="DM 버튼 문구" maxlength="20" required value="${esc(d.dm_button_text)}"><small class="prep-count" data-dm-button-count>${Array.from(d.dm_button_text || '').length} / 20</small></section>
          <footer class="prep-footer"><div><span data-save-status role="status">${data.revision?'저장된 초안':'새 초안 · 수정하면 자동 저장'}</span><small>현재는 초안 준비만 가능해요.</small></div><button type="submit">초안 저장</button></footer>
        </form></div></div>`;
      Object.keys(labels).forEach(key => { root.querySelector('[data-copy="'+key+'"]').value = d.thumbnail_options[key]; });
      root.querySelector('[name="prep-caption"]').value = d.caption;
      root.querySelector('[name="prep-comment"]').value = d.pinned_comment;
      root.querySelector('[name="prep-dm"]').value = d.dm_message || '';
      root.querySelector('[name="prep-dm-button"]').value = d.dm_button_text || '';
      // Each button reads its own current input, including changes not saved yet.
      root.querySelectorAll('.prep-option').forEach(option => option.insertAdjacentHTML('beforeend', copyControl(option.querySelector('textarea').getAttribute('aria-label'))));
      root.querySelectorAll('.prep-section').forEach(section => {
        const field = section.querySelector('[name^="prep-"]:is(textarea, input[type="text"])');
        if (field) section.insertAdjacentHTML('beforeend', copyControl(field.getAttribute('aria-label')));
      });
      root.querySelectorAll('[data-copy-text]').forEach(button => button.addEventListener('click', () => copyText(button)));
      root.querySelectorAll('video').forEach(player => player.addEventListener('play', () => {
        root.querySelectorAll('video').forEach(other => { if (other !== player) other.pause(); });
      }));
      root.querySelector('form').addEventListener('submit', event => { event.preventDefault(); save(true); });
      root.querySelector('form').addEventListener('input', changed);
      root.querySelector('[data-apply-thumbnail]').addEventListener('click',applyThumbnail);
      thumbnailFeedback();
      if (['queued','running'].includes(data.thumbnail?.status)) pollThumbnail();
    }
    fetch(endpoint, {signal:controller.signal, cache:'no-store'}).then(async response => {
      const result = await response.json(); if (!response.ok) throw new Error(result.error || '화면을 불러오지 못했어요.');
      if (!closed) { data = result; draftCache = result.draft; render(); }
    }).catch(error => { if (!closed) { root.innerHTML = '<div class="prep-loading" role="alert">불러오지 못했어요. 화면을 닫고 다시 열어 주세요.</div>'; } });
    const leave = () => save();
    window.addEventListener('pagehide', leave);
    return {close() { if (closed) return; save(); closed = true; controller.abort(); clearTimeout(timer); clearTimeout(thumbnailTimer); window.removeEventListener('pagehide', leave); }};
  }
  window.PostPreparation = {mount};
})();
