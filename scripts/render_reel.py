/**
 * ============================================================
 *  ninomae ONLINE 商品リール動画 → Instagram 自動投稿
 *
 *  流れ（すべて日本時間）
 *   1. 月・水・金の19時台：商品をランダムに選び、Geminiで動画の文字とキャプションを作り、
 *      GitHub（ninomae-reels）に動画づくりを依頼する
 *   2. GitHub が15秒の縦長動画を作り、GitHub Pages に公開する（2〜5分）
 *   3. 20〜22時のランダムな時刻：公開された動画をリールとして Instagram に投稿する
 *
 *  ※ product_auto_post.gs と同じプロジェクトに「新しいファイル」として追加してください。
 *    商品の取得・Gemini・Instagram投稿の部品はそちらの関数を共用しています。
 * ============================================================
 */

// ===== 設定 =====
const REEL_CONFIG = {
  PAUSED: false,                    // true にするとリールの自動投稿を一時停止

  GITHUB_OWNER: 'ninomae-hash',     // GitHub のユーザー名
  GITHUB_REPO: 'ninomae-reels',     // リポジトリ名
  PROP_GITHUB_TOKEN: 'GITHUB_TOKEN',// スクリプトプロパティに登録する GitHub のトークン名

  DAYS: [1, 3, 5],                  // 投稿する曜日（1=月 2=火 3=水 4=木 5=金 6=土 7=日）
  PREPARE_HOUR: 19,                 // 動画づくりを依頼する時刻（19時台）
  PUBLISH_START_HOUR: 20,           // 投稿の時間帯：開始
  PUBLISH_END_HOUR: 22,             // 投稿の時間帯：終了（この間のランダムな時刻）
  RETRY_UNTIL_HOUR: 23,             // うまくいかないときの再挑戦はこの時刻まで

  SHARE_TO_FEED: true,              // リールをプロフィールのフィード（投稿一覧）にも表示する
  POST_TO_FACEBOOK: true,           // Facebookページにも動画を投稿する
  BRAND: 'ninomae ONLINE',          // 動画の上部に出す名前

  // Instagramへの投稿方法
  //   false：自動投稿しない。動画ができたら、Instagram用とTikTok用のキャプションをメールで送る
  //          → アプリで流行の曲を付けて手動で投稿（Facebookへは投稿画面の「Facebookにもシェア」で）
  //   true ：Instagramへ自動投稿（API投稿のため曲は付けられず、無音のリールになります）
  INSTAGRAM_AUTO_POST: false,

  // 投稿用メール（動画の添付とキャプション）
  TIKTOK_MAIL: true,
  TIKTOK_MAIL_TO: 'info.ninomae@gmail.com',
};

const REEL_STATE = {
  JOB: 'REEL_JOB',                  // 進行中のリール（1件）
  ROTATED: 'REEL_ROTATED_IDS',      // 今の周回でリールにした商品
};

const REEL_TZ = 'Asia/Tokyo';


// ============================================================
//  1. セットアップ・テスト用（手動で実行）
// ============================================================

/** 設定の確認：GitHubのトークンとリポジトリにつながるかを確かめる */
function checkReelConfig() {
  const token = reelGithubToken_();
  if (!token) {
    Logger.log('⚠ スクリプトプロパティ「' + REEL_CONFIG.PROP_GITHUB_TOKEN + '」がありません。GitHubのトークンを登録してください');
    return;
  }
  const res = UrlFetchApp.fetch('https://api.github.com/repos/' + REEL_CONFIG.GITHUB_OWNER + '/' + REEL_CONFIG.GITHUB_REPO, {
    headers: reelGithubHeaders_(token), muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    Logger.log('⚠ リポジトリにつながりません（HTTP ' + res.getResponseCode() + '）。ユーザー名・リポジトリ名・トークンの権限を確認してください\n' + res.getContentText().slice(0, 300));
    return;
  }
  const repo = JSON.parse(res.getContentText());
  Logger.log('✅ GitHub OK：' + repo.full_name + '（' + (repo.private ? '非公開' : '公開') + '）');
  if (repo.private) Logger.log('⚠ リポジトリが「非公開」です。GitHub Pages で動画を公開するには「公開（Public）」にしてください');
  Logger.log('■ 動画の公開先：' + reelPagesBase_() + '/reels/');
  Logger.log('■ 投稿する曜日：' + REEL_CONFIG.DAYS.map(d => '月火水木金土日'.charAt(d - 1)).join('・')
    + '／' + REEL_CONFIG.PUBLISH_START_HOUR + '〜' + REEL_CONFIG.PUBLISH_END_HOUR + '時（日本時間）');
}

/** 【動画だけ作る】ランダムな商品で動画を作り、公開URLをログに出す（Instagramには投稿しない） */
function reelTestRender() {
  const item = reelPickItem_(false);
  if (!item) return;
  const texts = reelBuildSlides_(item);
  const jobId = Utilities.formatDate(new Date(), REEL_TZ, 'yyyyMMdd-HHmm') + '-test-' + item.id;
  reelDispatch_(reelPayload_(jobId, item, texts));
  Logger.log('🎬 動画づくりを依頼しました：' + item.name);
  Logger.log('　動画の文字：' + texts.slides.join(' ／ ') + ' ／（問いかけ）' + texts.question);
  Logger.log('→ 3〜5分後に次のURLを開くと動画を確認できます\n' + reelVideoUrl_(jobId));
}

/** 【今すぐ1本】曜日に関係なく動画を作り、約8分後に投稿用メールを送る（自動投稿モードならInstagramへ投稿） */
function reelPostNow() {
  reelPrepare_({ publishInMinutes: 8 });
}

/** トリガーを設定する（毎日19時台に「今日は投稿日か」を確認し、投稿日なら準備する） */
function setupReelTriggers() {
  reelDeleteTriggers_(['reelDailyPrepare', 'reelPrepareRetry', 'reelPublish']);
  ScriptApp.newTrigger('reelDailyPrepare').timeBased()
    .atHour(REEL_CONFIG.PREPARE_HOUR).everyDays(1).inTimezone(REEL_TZ).create();
  Logger.log('✅ リールのトリガーを設定しました（毎日' + REEL_CONFIG.PREPARE_HOUR + '時台に確認 → 投稿日なら'
    + REEL_CONFIG.PUBLISH_START_HOUR + '〜' + REEL_CONFIG.PUBLISH_END_HOUR + '時に'
    + (REEL_CONFIG.INSTAGRAM_AUTO_POST ? 'Instagramへ自動投稿' : '投稿用メールを送信') + '）');
}

/** 今の状況を確認する */
function reelStatus() {
  const job = productGetJson_(REEL_STATE.JOB, null);
  Logger.log(job ? '進行中のリール：\n' + JSON.stringify(job, null, 2) : '進行中のリールはありません');
  const rotated = productGetJson_(REEL_STATE.ROTATED, []);
  Logger.log('今の周回でリールにした商品：' + rotated.length + '件');
  ScriptApp.getProjectTriggers()
    .filter(t => /^reel/.test(t.getHandlerFunction()))
    .forEach(t => Logger.log('トリガー：' + t.getHandlerFunction()));
}

/** 進行中のリールを取り消す（投稿予約も消す） */
function reelCancel() {
  PropertiesService.getScriptProperties().deleteProperty(REEL_STATE.JOB);
  reelDeleteTriggers_(['reelPublish', 'reelPrepareRetry']);
  Logger.log('進行中のリールと投稿予約を取り消しました');
}


// ============================================================
//  2. トリガーで動く関数
// ============================================================

/** 毎日19時台：投稿日なら準備する */
function reelDailyPrepare() {
  if (REEL_CONFIG.PAUSED) { Logger.log('リールの自動投稿は一時停止中です'); return; }
  const weekday = Number(Utilities.formatDate(new Date(), REEL_TZ, 'u')); // 1=月〜7=日
  if (REEL_CONFIG.DAYS.indexOf(weekday) < 0) { Logger.log('今日はリールの投稿日ではありません'); return; }
  reelPrepare_({});
}

/** Geminiの一時的な失敗などで準備をやり直すとき用 */
function reelPrepareRetry() {
  reelDeleteTriggers_(['reelPrepareRetry']);
  if (REEL_CONFIG.PAUSED) return;
  reelPrepare_({});
}

/** 動画の公開を待って Instagram にリールとして投稿する */
function reelPublish() {
  reelDeleteTriggers_(['reelPublish']);
  const locked = productWithLock_(() => {
    const job = productGetJson_(REEL_STATE.JOB, null);
    if (!job || job.status === 'done') { Logger.log('投稿待ちのリールはありません'); return; }

    if (Date.now() > (job.deadline || reelTodayAt_(REEL_CONFIG.RETRY_UNTIL_HOUR).getTime())) {
      PropertiesService.getScriptProperties().deleteProperty(REEL_STATE.JOB);
      throw new Error('リールを時間内に投稿できなかったため、今日は見送りました（' + job.itemName + '）。最後の状況：' + (job.lastNote || '不明'));
    }

    // ① 動画が公開されているか確認
    if (!job.containerId) {
      const check = UrlFetchApp.fetch(job.videoUrl, { muteHttpExceptions: true, followRedirects: true });
      if (check.getResponseCode() !== 200) {
        reelSaveNote_(job, '動画の公開待ち（HTTP ' + check.getResponseCode() + '）');
        reelScheduleRetry_(10, '動画がまだ公開されていません');
        return;
      }

      // 手動投稿モード：Instagramには投稿せず、投稿用メールを送って完了
      if (!REEL_CONFIG.INSTAGRAM_AUTO_POST) {
        reelFinishManual_(job);
        return;
      }

      // ② Instagram にリールの下書き（コンテナ）を作る
      const ig = productIgBase_();
      try {
        const c = productIgCall_('post', ig.userId + '/media', {
          media_type: 'REELS',
          video_url: job.videoUrl,
          caption: job.caption,
          share_to_feed: REEL_CONFIG.SHARE_TO_FEED ? 'true' : 'false',
        });
        job.containerId = c.id;
        reelSaveNote_(job, 'Instagramで動画を処理中');
      } catch (e) {
        if (productIsFatalError_(e)) throw e;
        reelSaveNote_(job, 'コンテナ作成に失敗: ' + e.message);
        reelScheduleRetry_(15, e.message);
        return;
      }
    }

    // ③ Instagram 側の動画処理が終わるのを待つ（最大 約4分。終わらなければ5分後に続きから）
    for (let i = 0; i < 9; i++) {
      let st;
      try {
        st = productIgCall_('get', job.containerId, { fields: 'status_code,status' });
      } catch (e) {
        if (productIsFatalError_(e)) throw e;
        Utilities.sleep(20000);
        continue;
      }
      if (st.status_code === 'FINISHED') {
        reelFinish_(job);
        return;
      }
      if (st.status_code === 'ERROR' || st.status_code === 'EXPIRED') {
        PropertiesService.getScriptProperties().deleteProperty(REEL_STATE.JOB);
        throw new Error('Instagramが動画を受け付けませんでした（' + st.status_code + '）: ' + (st.status || '') + ' / ' + job.videoUrl);
      }
      Utilities.sleep(25000);
    }
    reelSaveNote_(job, 'Instagramで動画を処理中（時間がかかっています）');
    reelScheduleRetry_(5, 'Instagramの動画処理が終わっていません');
  });
  if (!locked) reelScheduleRetry_(5, '他の処理と重なったため');
}


// ============================================================
//  3. 中身の処理
// ============================================================

/** 商品を選び、文字とキャプションを作り、GitHubに動画づくりを依頼して、投稿を予約する */
function reelPrepare_(opts) {
  const existing = productGetJson_(REEL_STATE.JOB, null);
  if (existing && existing.status !== 'done' && existing.day === reelToday_()) {
    Logger.log('今日のリールはすでに準備済みです：' + existing.itemName);
    return;
  }

  const item = reelPickItem_(true);
  if (!item) return;

  let texts, caption;
  try {
    texts = reelBuildSlides_(item);
    caption = productBuildCaption_(item, 'rotation'); // 商品投稿と同じ型のキャプション
  } catch (e) {
    if (e.captionFailed || /Gemini/.test(e.message)) {
      if (reelHourJst_() < REEL_CONFIG.PUBLISH_END_HOUR - 1) {
        ScriptApp.newTrigger('reelPrepareRetry').timeBased().at(new Date(Date.now() + 30 * 60 * 1000)).create();
        Logger.log('⏸ 文字の作成に失敗したため、30分後にやり直します：' + e.message);
      } else {
        Logger.log('⏸ 文字の作成に失敗し、時間内にやり直せないため今日は見送ります：' + e.message);
      }
      return;
    }
    throw e;
  }

  const jobId = Utilities.formatDate(new Date(), REEL_TZ, 'yyyyMMdd-HHmm') + '-' + item.id;
  reelDispatch_(reelPayload_(jobId, item, texts));

  const job = {
    id: jobId, day: reelToday_(), itemId: item.id, itemName: item.name,
    videoUrl: reelVideoUrl_(jobId), caption: caption, status: 'rendering',
    slides: texts.slides, question: texts.question, url: item.url,
    price: item.price ? '¥' + item.price.toLocaleString('ja-JP') + '（税込）' : '',
  };
  productSetJson_(REEL_STATE.JOB, job);

  // 投稿時刻を決める（動画づくりに最低15分の余裕を見る）
  let runAt;
  if (opts && opts.publishInMinutes) {
    runAt = new Date(Date.now() + opts.publishInMinutes * 60 * 1000);
  } else {
    const start = reelTodayAt_(REEL_CONFIG.PUBLISH_START_HOUR).getTime();
    const end = reelTodayAt_(REEL_CONFIG.PUBLISH_END_HOUR).getTime();
    const from = Math.max(start, Date.now() + 15 * 60 * 1000);
    runAt = new Date(from >= end ? from : from + Math.floor(Math.random() * (end - from)));
  }
  // 再挑戦の期限：通常は23時。テストで夜遅くに実行した場合は投稿予定の2時間後まで
  job.deadline = Math.max(reelTodayAt_(REEL_CONFIG.RETRY_UNTIL_HOUR).getTime(), runAt.getTime() + 2 * 3600 * 1000);
  productSetJson_(REEL_STATE.JOB, job);
  reelDeleteTriggers_(['reelPublish']);
  ScriptApp.newTrigger('reelPublish').timeBased().at(runAt).create();

  Logger.log('🎬 リールを準備しました：' + item.name);
  Logger.log('　動画の文字：' + texts.slides.join(' ／ ') + ' ／（問いかけ）' + texts.question);
  Logger.log('📅 ' + Utilities.formatDate(runAt, REEL_TZ, 'M/d HH:mm') + '（日本時間）に投稿します');
  Logger.log('　動画URL：' + job.videoUrl);
}

/** 商品を1つ選ぶ（今の周回でまだリールにしていない商品からランダム。売り切れ・画像なしは除く） */
function reelPickItem_(useRotation) {
  const ids = productGetAllIds_();
  if (!ids.length) { Logger.log('商品一覧を取得できませんでした'); return null; }
  let rotated = useRotation ? productGetJson_(REEL_STATE.ROTATED, []) : [];
  let candidates = ids.filter(id => rotated.indexOf(id) < 0);
  if (!candidates.length) {
    candidates = ids;
    if (useRotation) { productSetJson_(REEL_STATE.ROTATED, []); Logger.log('全商品をリールにしたので最初から'); }
  }
  candidates = productShuffle_(candidates);
  for (let i = 0; i < candidates.length && i < 6; i++) {
    const item = productGetDetail_(candidates[i]);
    if (item && !item.soldOut && item.images.length) return item;
  }
  Logger.log('リールにできる商品が見つかりませんでした');
  return null;
}

/**
 * バズり型の動画に重ねる文字を Gemini で作る
 * 戻り値：{ slides: [つかみ, 一言1, 一言2, 一言3, 一言4], question: 問いかけ }
 */
function reelBuildSlides_(item) {
  const prompt = [
    'あなたはプリザーブドフラワー専門店「ninomae ONLINE」のTikTok・Instagramリール担当です。',
    '14秒の商品紹介動画に重ねる短い文字を作ってください。最初の1秒で指が止まる動画にしたいです。',
    '',
    '【作るもの】',
    '・hook（つかみ）：最初に大きく出す一言。8〜14文字。思わず続きを見たくなる問いかけや意外な事実',
    '　例：「枯れない花って知ってた？」「まだ生花を贈ってるの？」「この花、水やりいらないんです」',
    '・lines：2秒ごとに出す短い一言を4つ。各6〜12文字。テンポよく、商品の魅力→特長→贈るシーンの順',
    '　例：「手のひらサイズの幸せ」「水やり不要でずっと可愛い」「ちょっとしたお礼にぴったり」',
    '・question：最後に出す、コメントしたくなる問いかけ。16〜22文字',
    '　例：「あなたなら誰に贈る？コメントで教えてね」「何色が好き？コメントで教えてね」',
    '',
    '【条件】',
    '・絵文字・ハッシュタグ・記号の多用は禁止。話し言葉でやわらかく',
    '・商品名と価格は入れない（最後に別で表示します）',
    '・商品情報に書かれていないこと（サイズ・期限・効果など）は作らない。大げさな表現や「必ず」「絶対」は使わない',
    '',
    '【出力形式】次のJSONだけを出力：',
    '{"hook": "…", "lines": ["…", "…", "…", "…"], "question": "…"}',
    '',
    '【商品情報】',
    '商品名：' + item.name,
    '説明：' + item.description,
  ].join('\n');

  const tidy = v => String(v || '').replace(/[#＃]\S+/g, '').replace(/\s+/g, ' ').trim();
  let lastErr;
  for (let i = 0; i < 2; i++) {
    try {
      const raw = productCallGemini_(prompt, true);
      const m = String(raw).replace(/```[a-z]*/gi, '').match(/\{[\s\S]*\}/);
      if (!m) throw new Error('JSON形式で返ってきませんでした');
      const obj = JSON.parse(m[0]);
      const hook = tidy(obj.hook);
      const lines = (obj.lines || []).map(tidy).filter(Boolean).slice(0, 4);
      const question = tidy(obj.question);
      if (!hook || lines.length < 4) throw new Error('文字がそろいませんでした');
      return { slides: [hook].concat(lines), question: question || 'あなたなら誰に贈る？コメントで教えてね' };
    } catch (e) {
      lastErr = e;
      if (/Gemini API エラー/.test(e.message)) break; // API自体の失敗は作り直しても同じ
    }
  }
  const err = new Error('Gemini：動画の文字を作れませんでした: ' + (lastErr && lastErr.message));
  err.captionFailed = true;
  throw err;
}

function reelPayload_(jobId, item, texts) {
  return {
    job_id: jobId,
    images: item.images.slice(0, 6),      // 写真は最大6枚（テンポよく切り替えるため）
    slides: texts.slides,
    question: texts.question,
    title: item.name,
    price: item.price ? '¥' + item.price.toLocaleString('ja-JP') + '（税込）' : '',
    brand: REEL_CONFIG.BRAND,
  };
}

/** GitHub に「動画を作って」と依頼する */
function reelDispatch_(payload) {
  const token = reelGithubToken_();
  if (!token) throw new Error('スクリプトプロパティ「' + REEL_CONFIG.PROP_GITHUB_TOKEN + '」（GitHubのトークン）がありません');
  const res = UrlFetchApp.fetch('https://api.github.com/repos/' + REEL_CONFIG.GITHUB_OWNER + '/' + REEL_CONFIG.GITHUB_REPO + '/dispatches', {
    method: 'post',
    contentType: 'application/json',
    headers: reelGithubHeaders_(token),
    payload: JSON.stringify({ event_type: 'render-reel', client_payload: payload }),
    muteHttpExceptions: true,
  });
  const code = res.getResponseCode();
  if (code !== 204) {
    throw new Error('GitHubへの依頼に失敗しました（HTTP ' + code + '）。'
      + (code === 401 ? 'トークンが無効か期限切れです。' : code === 403 || code === 404 ? 'トークンの権限（Contents: Read and write）とリポジトリ名を確認してください。' : '')
      + res.getContentText().slice(0, 200));
  }
}

/** 投稿完了の処理 */
function reelFinish_(job) {
  const ig = productIgBase_();
  const pub = productIgCall_('post', ig.userId + '/media_publish', { creation_id: job.containerId });
  job.status = 'done';
  job.mediaId = pub.id;
  job.lastNote = '投稿完了';
  productSetJson_(REEL_STATE.JOB, job);

  const rotated = productGetJson_(REEL_STATE.ROTATED, []);
  if (rotated.indexOf(job.itemId) < 0) { rotated.push(job.itemId); productSetJson_(REEL_STATE.ROTATED, rotated); }
  Logger.log('✅ リールを投稿しました：' + job.itemName + ' / Media ID: ' + pub.id);

  if (REEL_CONFIG.POST_TO_FACEBOOK) {
    try {
      reelFbPostVideo_(job.videoUrl, job.caption);
    } catch (e) {
      Logger.log('Facebook動画の投稿失敗: ' + e.message
        + (/access token|session/i.test(e.message) ? '\n→ FB_PAGE_ACCESS_TOKEN が無効です。ページアクセストークンを再発行してください' : ''));
    }
  }

  if (REEL_CONFIG.TIKTOK_MAIL) {
    try {
      reelSendTiktokMail_(job, false);
    } catch (e) {
      Logger.log('TikTok用メールの送信失敗: ' + e.message);
    }
  }
}


// ============================================================
//  TikTok用（半自動）：動画とキャプションをメールで送る → スマホのTikTokアプリから投稿
// ============================================================

/** TikTok用の短いキャプションを作る（ハッシュタグはInstagramと同じ5個） */
function reelTiktokCaption_(job) {
  const name = String(job.itemName || '');
  const m = name.match(/[「『](.+?)[」』]/);
  const shortName = m ? m[1] : name.split(/[｜|]/)[0].trim();
  const tagLine = String(job.caption || '').split('\n').filter(l => /^\s*#/.test(l)).pop()
    || productBuildHashtags_([]);
  return [
    (job.slides && job.slides[0]) ? job.slides[0] : '',
    shortName + (job.price ? '　' + job.price : ''),
    '商品はプロフィールのリンクから',
    job.question || '',
    '',
    tagLine,
  ].filter((l, i) => l || i === 4).join('\n').trim();
}

/** 手動投稿モードの完了処理：投稿用メール（Instagram・TikTok）を送る */
function reelFinishManual_(job) {
  reelSendTiktokMail_(job, true);
  job.status = 'done';
  job.lastNote = '投稿用メールを送信';
  productSetJson_(REEL_STATE.JOB, job);
  const rotated = productGetJson_(REEL_STATE.ROTATED, []);
  if (rotated.indexOf(job.itemId) < 0) { rotated.push(job.itemId); productSetJson_(REEL_STATE.ROTATED, rotated); }
  Logger.log('✅ リール動画を用意し、投稿用メールを送りました：' + job.itemName);
}

/**
 * 投稿用メールを送る（動画を添付）
 * withInstagram が true のときは、Instagram用のキャプションと手順も入れる
 */
function reelSendTiktokMail_(job, withInstagram) {
  const ttCaption = reelTiktokCaption_(job);
  const igCaption = job.caption || '';
  const day = Utilities.formatDate(new Date(), REEL_TZ, 'M/d');
  const label = withInstagram ? '【Instagram・TikTok用】' : '【TikTok用】';
  const subject = label + 'リール動画 ' + day + '：' + String(job.itemName || '').split(/[｜|]/)[0].trim();

  // 動画を添付（スマホでそのまま保存できるように）。取得できなければリンクだけ送る
  const attachments = [];
  try {
    const res = UrlFetchApp.fetch(job.videoUrl, { muteHttpExceptions: true });
    if (res.getResponseCode() === 200) attachments.push(res.getBlob().setName('ninomae_' + job.id + '.mp4').setContentType('video/mp4'));
  } catch (e) {}

  const sections = [];
  if (withInstagram) {
    sections.push({
      title: 'Instagram（リール）',
      steps: ['添付の動画をスマホに保存', 'Instagramアプリの「＋」→「リール」→ 動画を選ぶ',
              '「音楽」から流行の曲を選ぶ（動画は無音です）', '「次へ」→ 下のキャプションを貼り付け',
              '「Facebookにおすすめ」（Facebookにもシェア）をオンにして「シェア」'],
      caption: igCaption,
    });
  }
  sections.push({
    title: 'TikTok',
    steps: ['添付の動画をスマホに保存', 'TikTokアプリの「＋」→ 動画を選ぶ',
            '「サウンドを追加」で流行の曲を選ぶ（動画は無音です）', '下のキャプションを貼り付けて投稿'],
    caption: ttCaption,
  });

  const esc = v => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const lines = ['今日のリール動画をお送りします。投稿は1つにつき約1分です。', ''];
  let html = '<div style="font-family:sans-serif;line-height:1.7"><p>今日のリール動画をお送りします。投稿は1つにつき約1分です。</p>';
  sections.forEach(sec => {
    lines.push('━━━━━━━━━━', '■ ' + sec.title, '━━━━━━━━━━');
    sec.steps.forEach((st, k) => lines.push((k + 1) + '. ' + st));
    lines.push('', '▼ キャプション（ここから下をコピー）', sec.caption, '');
    html += '<h3 style="color:#996691;border-bottom:2px solid #ecb8c4;padding-bottom:4px">' + esc(sec.title) + '</h3>'
      + '<p>' + sec.steps.map((st, k) => (k + 1) + '. ' + esc(st)).join('<br>') + '</p>'
      + '<p><b>キャプション</b>（枠の中を長押しでコピー）</p>'
      + '<pre style="white-space:pre-wrap;background:#f6f1f3;padding:12px;border-radius:8px;font-family:sans-serif">' + esc(sec.caption) + '</pre>';
  });
  lines.push('■ 動画リンク', job.videoUrl, '', '■ 商品ページ', job.url || '');
  html += '<p><b>動画リンク</b><br><a href="' + esc(job.videoUrl) + '">' + esc(job.videoUrl) + '</a></p>'
    + (job.url ? '<p><b>商品ページ</b><br><a href="' + esc(job.url) + '">' + esc(job.url) + '</a></p>' : '')
    + '</div>';

  MailApp.sendEmail({ to: REEL_CONFIG.TIKTOK_MAIL_TO, subject: subject, body: lines.join('\n'), htmlBody: html, attachments: attachments, name: 'ninomae 自動投稿' });
  Logger.log('📩 投稿用の動画とキャプションを ' + REEL_CONFIG.TIKTOK_MAIL_TO + ' に送りました' + (attachments.length ? '（動画添付あり）' : '（リンクのみ）'));
}

/** 【テスト】直近のリールで、投稿用メールをもう一度送る */
function reelTestTiktokMail() {
  const job = productGetJson_(REEL_STATE.JOB, null);
  if (!job) { Logger.log('送れるリールがありません。先に reelPostNow などでリールを1本作ってください'); return; }
  reelSendTiktokMail_(job, !REEL_CONFIG.INSTAGRAM_AUTO_POST);
}

function reelFbPostVideo_(videoUrl, description) {
  const props = PropertiesService.getScriptProperties();
  const pageId = props.getProperty(PRODUCT_CONFIG.PROP_FB_PAGE_ID);
  const token = props.getProperty(PRODUCT_CONFIG.PROP_FB_TOKEN);
  if (!pageId || !token) { Logger.log('FB設定がないためFacebook投稿はスキップ'); return; }
  const res = UrlFetchApp.fetch('https://graph.facebook.com/' + PRODUCT_CONFIG.GRAPH_VERSION + '/' + pageId + '/videos', {
    method: 'post',
    payload: { file_url: videoUrl, description: description, access_token: token },
    muteHttpExceptions: true,
  });
  const json = JSON.parse(res.getContentText());
  if (json.error) throw new Error(json.error.message);
  Logger.log('✅ Facebookにも動画を投稿しました: ' + json.id);
}


// ============================================================
//  4. 小さな部品
// ============================================================

function reelGithubToken_() {
  return (PropertiesService.getScriptProperties().getProperty(REEL_CONFIG.PROP_GITHUB_TOKEN) || '').trim();
}

function reelGithubHeaders_(token) {
  return { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
}

function reelPagesBase_() {
  return 'https://' + REEL_CONFIG.GITHUB_OWNER.toLowerCase() + '.github.io/' + REEL_CONFIG.GITHUB_REPO;
}

function reelVideoUrl_(jobId) {
  return reelPagesBase_() + '/reels/' + jobId + '.mp4';
}

function reelToday_() {
  return Utilities.formatDate(new Date(), REEL_TZ, 'yyyy-MM-dd');
}

function reelHourJst_() {
  return Number(Utilities.formatDate(new Date(), REEL_TZ, 'H'));
}

function reelTodayAt_(hour) {
  return new Date(reelToday_() + 'T' + ('0' + hour).slice(-2) + ':00:00+09:00');
}

function reelSaveNote_(job, note) {
  job.lastNote = note;
  productSetJson_(REEL_STATE.JOB, job);
}

/** 数分後に reelPublish をもう一度動かす */
function reelScheduleRetry_(minutes, reason) {
  const runAt = new Date(Date.now() + minutes * 60 * 1000);
  reelDeleteTriggers_(['reelPublish']);
  ScriptApp.newTrigger('reelPublish').timeBased().at(runAt).create();
  Logger.log('⏸ ' + reason + ' → ' + Utilities.formatDate(runAt, REEL_TZ, 'HH:mm') + '（日本時間）に再挑戦します');
}

function reelDeleteTriggers_(names) {
  ScriptApp.getProjectTriggers()
    .filter(t => names.indexOf(t.getHandlerFunction()) >= 0)
    .forEach(t => ScriptApp.deleteTrigger(t));
}
