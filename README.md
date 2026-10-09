# 朝のニュース

毎朝、指定したジャンルのニュースを主要サイト（NHK・Yahoo!ニュース・ITmedia・Googleニュース経由の各紙）から集め、
要点を一覧表示し、読み上げ音声で聴けるWebアプリです。スマホのブラウザで使えます。

- 収集・要約・音声生成は GitHub Actions が毎朝 5:30ごろ（日本時間）に自動実行
- 要約はAPIを使わない抽出型（記事の概要文の先頭数文）
- 音声は edge-tts（Microsoft Edge の無料読み上げ音声）
- すべて無料で動きます

## セットアップ（初回のみ）

1. GitHub で新しいリポジトリを作成（例: `morning-news`、**Public**）
2. このフォルダの中身を push
   ```
   git init
   git add .
   git commit -m "first commit"
   git branch -M main
   git remote add origin https://github.com/<ユーザー名>/morning-news.git
   git push -u origin main
   ```
3. リポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** に変更
4. **Actions** タブ →「朝のニュース生成」→ **Run workflow** で1回手動実行
5. 数分後、`https://<ユーザー名>.github.io/morning-news/` を開く
6. スマホではブラウザの「ホーム画面に追加」でアプリのように使えます

## 設定の変更

`config.yaml` などを編集して push すると、自動でニュースを作り直して数分で公開ページに反映されます。

- ジャンルの追加・削除、ジャンルごとの記事数（`max_items`）
- フィード（RSSのURL）
- 声（`ja-JP-NanamiNeural` / `ja-JP-KeitaNeural`）と読み上げ速度
- キーワードで絞るジャンルは `title_keywords` を指定（例: コールセンター）

## PCで試す

Python 3.10 以上が必要です。

```
pip install -r requirements.txt
python scripts/build.py
python -m http.server -d docs 8000
```

ブラウザで http://localhost:8000 を開きます。

## キャスター（リップシンク）

画面上部のキャスターは、AIで生成した**架空の人物**です（実在の人物ではありません）。

- 写真：ローカル ComfyUI の日本人写実系 SDXL（fuduki_mix v2.0）で生成
- 口の形：その写真から Wan2.2 TI2V-5B で「頭を動かさずに母音を発音する」動画を作り、そのコマから「あ・い・う・え・お」の口を切り出して、口を閉じた写真（`docs/anchor/base.jpg`）に位置と肌色を合わせた画像にした（`docs/anchor/a.png` など。作り方は `assets/anchor/make_visemes.py`）。まばたきも同様
- 同期：ニュース生成時に、音声エンジンの単語ごとの発話タイミングと、単語の読み（pykakasi でローマ字化）から母音の並びを記録（`docs/data/speech.json` = [開始秒, 長さ秒, "uou", ...]）。画面では再生位置から今の音を計算して口の画像を切り替える（`docs/anchor.js`）
- ブラウザで音声を解析しないので、iPhoneの画面ロック中も再生が止まらない

## 注意

- 無料の GitHub Pages は公開リポジトリが前提のため、URLを知っていれば誰でもページを見られます（中身はニュースの見出しと短い抜粋、元記事へのリンク）。
- GitHub の定期実行は、リポジトリに **60日間** 更新がないと自動停止します。停止したらメールが届くので、Actions 画面から再度有効にしてください。
- Googleニュース経由の記事は概要文が取れないことが多く、タイトルのみの読み上げになります。
- edge-tts は公式APIではないため、将来使えなくなる可能性があります。
