/* Pure dashboard queries. Detection dates remain owned by hot-detection.js. */
(function (root) {
  'use strict';

  function create(detection) {
    const isVideo = post => post.kind === 'reel' || post.kind === 'video';

    function baseFiltered(posts, state, now = Date.now() / 1000) {
      const query = state.q;
      return posts.filter(post => {
        if (post.ranking_mode === 'views_per_follower_72h') {
          if (!post.eligible) return false;
        } else if (state.detection === 'today') {
          if (!detection.isToday(post, now)) return false;
        } else if (!detection.withinHours(post, state.period, now)) return false;
        if (state.kind === 'video' && !isVideo(post)) return false;
        if (state.kind === 'image' && isVideo(post)) return false;
        if (state.account && post.username !== state.account) return false;
        if (query && !(post.caption.toLowerCase().includes(query) ||
          post.username.includes(query) ||
          post.hashtags.some(tag => tag.includes(query.replace(/^#/, ''))))) return false;
        return true;
      });
    }

    function filtered(base, state, now = Date.now() / 1000) {
      const list = base.filter(post => {
        if (post.tier < state.tier) return false;
        if (post.ranking_mode !== 'views_per_follower_72h' && state.assessment !== 'all' && post.assessment?.status !== state.assessment) return false;
        if (state.topic && !(post.categories || ['생활·기타']).includes(state.topic)) return false;
        return true;
      });
      const key = {
        rank: post => post.rank_score,
        views: post => post.views || 0,
        comments: post => post.comments,
        likes: post => post.likes,
        recent: post => post.hot_detected_at,
      }[state.sort];
      return list.sort((a, b) => state.sort === 'rank' && a.ranking_mode === 'views_per_follower_72h'
        ? a.rank - b.rank : detection.compare(a, b, key, now));
    }

    function topics(base, state) {
      const groups = new Map();
      for (const post of base) {
        if (post.tier < Math.max(1, state.tier) ||
          (post.ranking_mode !== 'views_per_follower_72h' && state.assessment !== 'all' && post.assessment?.status !== state.assessment)) continue;
        for (const label of post.categories || ['생활·기타']) {
          if (!groups.has(label)) groups.set(label, {label, posts: 0, score: 0, accounts: new Set()});
          const group = groups.get(label);
          group.posts++;
          group.score += post.tier;
          group.accounts.add(post.username);
        }
      }
      return [...groups.values()]
        .sort((a, b) => (a.label === '생활·기타') - (b.label === '생활·기타') || b.score - a.score)
        .map(group => ({...group, accounts: group.accounts.size}));
    }

    // Header totals describe the whole Korean day, independently of card filters.
    function dailyStats(posts, now = Date.now() / 1000) {
      const daily = posts.some(post => post.ranking_mode === 'views_per_follower_72h');
      const hot = posts.filter(post => daily ? post.eligible : detection.isToday(post, now));
      return {
        day: detection.dateKey(now),
        total: hot.length,
        confirmed: hot.filter(post => post.assessment?.status === 'confirmed').length,
        provisional: hot.filter(post => post.assessment?.status !== 'confirmed').length,
        accounts: new Set(hot.map(post => post.username)).size,
        videoPercent: Math.round(hot.filter(isVideo).length / Math.max(1, hot.length) * 100),
      };
    }

    return {baseFiltered, filtered, topics, dailyStats};
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {create};
  else root.HotpostDiscovery = {create};
})(globalThis);
