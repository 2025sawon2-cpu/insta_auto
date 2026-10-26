(function () {
  'use strict';
  const labels = {recommended:'기본 제작 문구', hook:'후킹 강한 문구', curiosity:'궁금증을 부르는 문구', benefit:'사용했을 때의 이득'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function mount(root, post) {
    let closed = false, data, draftCache, timer, saving = false, pendingSave, version = 0, savedVersion = 0, conflict = false;
    let thumbnailTimer, applying = false;
    let coupangTimer, findingLink = false;
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
    function changed(event) {
      if (event?.target.closest('[data-coupang-controls]')) { coupangFeedback(); return; }
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
      const section = button.closest('.prep-section');
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
    function coupangInput() {
      return {product_name:root.querySelector('[name="coupang-name"]').value.trim(),
        storefront_url:root.querySelector('[name="coupang-store"]').value.trim(),
        product_url:root.querySelector('[name="coupang-product"]').value.trim(),
        register:Boolean(root.querySelector('[name="coupang-register"]').checked)};
    }
    function coupangFeedback() {
      if (closed || !data) return;
      const state=data.coupang_link || {}, running=findingLink || state.status==='running';
      const button=root.querySelector('[data-find-coupang]'), notice=root.querySelector('[data-coupang-status]');
      if (!button || !notice) return;
      button.disabled=running || conflict || !data.media.final || !data.coupang_link;
      button.textContent=running?'원링크 확인 중…':'쿠팡 원링크 찾기';
      notice.textContent=!data.coupang_link ? '원링크 기능이 아직 연결되지 않았습니다. 연결 상태를 확인하세요.' :
        state.message || '제품명 풀네임과 내 스토어를 입력하세요. 버튼을 눌렀을 때만 실행합니다.';
      notice.classList.toggle('is-error',['failed','interrupted'].includes(state.status));
      notice.setAttribute('aria-busy',String(running));
      const result=state.result || {}, input=coupangInput(), payload=state.payload || {};
      const same=['product_name','storefront_url','product_url'].every(key=>input[key]===payload[key]);
      const ready=state.status==='completed' && result.landing_verified===true;
      root.querySelector('[data-coupang-result]').textContent=ready
        ? `${result.title} · 상품 ${result.product_id} / 옵션 ${result.item_id} / 판매옵션 ${result.vendor_item_id}\n${result.one_link}` : '';
      const apply=root.querySelector('[data-use-coupang]');
      apply.hidden=!ready; apply.disabled=!same || running;
    }
    async function pollCoupang() {
      clearTimeout(coupangTimer);
      if (closed) return;
      try {
        const response=await fetch(endpoint,{signal:controller.signal,cache:'no-store'});
        if (!response.ok) throw new Error('status');
        const fresh=await response.json();
        if (closed) return;
        data.coupang_link=fresh.coupang_link; coupangFeedback();
        if (data.coupang_link?.status==='running') coupangTimer=setTimeout(pollCoupang,1500);
      } catch (_) {
        if (!closed) {
          root.querySelector('[data-coupang-status]').textContent='결과를 불러오지 못했습니다. 연결을 다시 확인하고 있습니다. 요청을 다시 실행하지 않습니다.';
          coupangTimer=setTimeout(pollCoupang,3000);
        }
      }
    }
    async function findCoupang() {
      if (findingLink || data.coupang_link?.status==='running') return;
      const input=coupangInput(); findingLink=true; coupangFeedback();
      try {
        let okay=await save();
        if (okay && savedVersion!==version) okay=await save();
        if (!okay || savedVersion!==version) throw new Error('초안 저장 상태를 확인한 뒤 다시 실행하세요.');
        if (closed) return;
        const response=await fetch(endpoint+'/coupang-link',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({revision:data.revision,...input})});
        const result=await response.json();
        if (closed) return;
        if (!response.ok) throw new Error(result.error || '원링크 요청을 시작하지 못했습니다.');
        data.coupang_link=result; findingLink=false; coupangFeedback(); pollCoupang();
      } catch (error) {
        if (!closed) { data.coupang_link={status:'failed',message:error.message}; findingLink=false; coupangFeedback(); }
      }
    }
    function useCoupang() {
      const state=data.coupang_link || {}, input=coupangInput();
      if (closed || state.status!=='completed' || !state.result?.landing_verified ||
          !['product_name','storefront_url','product_url'].every(key=>input[key]===state.payload[key])) return;
      root.querySelector('[name="prep-link"]').value=state.result.one_link;
      changed();
      root.querySelector('[data-coupang-status]').textContent='확인한 원링크를 제품 링크에 넣었습니다. 초안에 저장합니다.';
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
          <section class="prep-section"><h3><span>05</span> 쿠팡 인플루언서 제품 링크</h3><p class="prep-help">내 스토어에서 원링크를 찾고 실제 연결 상품을 확인합니다. 결과를 확인한 뒤 사용 버튼을 누르세요.</p><input name="prep-link" type="text" inputmode="url" aria-label="쿠팡 인플루언서 제품 링크" maxlength="2048" placeholder="제품 링크를 입력하세요" value="${esc(d.product_link)}"><div class="prep-coupang" data-coupang-controls>
            <label>제품명 풀네임<input type="text" name="coupang-name" aria-label="쿠팡 검색 제품명" maxlength="300" placeholder="브랜드와 모델명을 포함한 제품명"></label>
            <label>내 쿠팡 인플루언서 스토어<input type="text" name="coupang-store" aria-label="내 쿠팡 인플루언서 스토어" inputmode="url" maxlength="2048" placeholder="https://influencers.coupang.com/s/내스토어"></label>
            <label>원 상품 URL (선택)<input type="text" name="coupang-product" aria-label="쿠팡 원 상품 URL" inputmode="url" maxlength="2048" placeholder="상품·옵션을 정확히 지정할 때 입력"></label>
            <label class="prep-coupang-register"><input type="checkbox" name="coupang-register">없으면 파트너스 링크를 생성하고 내 스토어 첫 컬렉션에 등록</label>
            <p class="prep-help">등록 옵션을 선택하면 기존 로그인 Chrome에서 스토어를 변경합니다. 새 로그인 창은 열지 않습니다.</p>
            <button type="button" data-find-coupang>쿠팡 원링크 찾기</button><p data-coupang-status role="status" aria-live="polite"></p><p data-coupang-result></p><button type="button" data-use-coupang hidden>이 원링크 사용</button>
          </div></section>
          <section class="prep-section"><h3><span>06</span> DM으로 보낼 메시지</h3><p class="prep-help">모든 게시물에 공통으로 사용하는 고정 안내 문구예요.</p><textarea name="prep-dm" aria-label="DM으로 보낼 메시지" rows="5" readonly>${esc(d.dm_message)}</textarea></section>
          <section class="prep-section"><h3><span>07</span> DM 버튼 문구</h3><p class="prep-help">주제를 후킹하는 20자 이내 한 줄이에요. 원하는 문구로 수정할 수 있어요.</p><input name="prep-dm-button" type="text" aria-label="DM 버튼 문구" maxlength="20" required value="${esc(d.dm_button_text)}"><small class="prep-count" data-dm-button-count>${Array.from(d.dm_button_text || '').length} / 20</small></section>
          <footer class="prep-footer"><div><span data-save-status role="status">${data.revision?'저장된 초안':'새 초안 · 수정하면 자동 저장'}</span><small>현재는 초안 준비만 가능해요.</small></div><button type="submit">초안 저장</button></footer>
        </form></div></div>`;
      Object.keys(labels).forEach(key => { root.querySelector('[data-copy="'+key+'"]').value = d.thumbnail_options[key]; });
      root.querySelector('[name="prep-caption"]').value = d.caption;
      root.querySelector('[name="prep-comment"]').value = d.pinned_comment;
      root.querySelector('[name="prep-dm"]').value = d.dm_message || '';
      root.querySelector('[name="prep-dm-button"]').value = d.dm_button_text || '';
      const query=data.coupang_link?.payload || {};
      root.querySelector('[name="coupang-name"]').value=query.product_name || '';
      root.querySelector('[name="coupang-store"]').value=query.storefront_url || '';
      root.querySelector('[name="coupang-product"]').value=query.product_url || '';
      // Each button reads its own current input, including changes not saved yet.
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
      root.querySelector('[data-find-coupang]').addEventListener('click',findCoupang);
      root.querySelector('[data-use-coupang]').addEventListener('click',useCoupang);
      coupangFeedback();
      if (data.coupang_link?.status==='running') pollCoupang();
      thumbnailFeedback();
      if (['queued','running'].includes(data.thumbnail?.status)) pollThumbnail();
    }
    fetch(endpoint, {signal:controller.signal, cache:'no-store'}).then(async response => {
      const result = await response.json(); if (!response.ok) throw new Error(result.error || '화면을 불러오지 못했어요.');
      if (!closed) { data = result; draftCache = result.draft; render(); }
    }).catch(error => { if (!closed) { root.innerHTML = '<div class="prep-loading" role="alert">불러오지 못했어요. 화면을 닫고 다시 열어 주세요.</div>'; } });
    const leave = () => save();
    window.addEventListener('pagehide', leave);
    return {close() { if (closed) return; save(); closed = true; controller.abort(); clearTimeout(timer); clearTimeout(thumbnailTimer); clearTimeout(coupangTimer); window.removeEventListener('pagehide', leave); }};
  }
  window.PostPreparation = {mount};
})();
