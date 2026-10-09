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

## 3Dキャスター

画面上部の3Dアバターは、pixiv社が公開しているサンプルモデル
[VRM1_Constraint_Twist_Sample](https://github.com/vrm-c/vrm-specification/tree/master/samples/VRM1_Constraint_Twist_Sample)
（© 2022 pixiv Inc.、[VRM Public License 1.0](https://vrm.dev/licenses/1.0/)：誰でも利用可・再配布可・クレジット表記不要）を
`docs/avatar/caster.vrm` として使っています。表示には [three.js](https://threejs.org/) と [three-vrm](https://github.com/pixiv/three-vrm) を使います。

口パクは、ニュース生成時に音声エンジンから受け取った単語ごとの発話タイミング（`docs/data/speech.json`）に合わせて動かしています。
ブラウザで音声を解析しないので、iPhoneの画面ロック中も再生が止まりません。

別のVRMモデルに差し替えるときは、`docs/avatar/caster.vrm` を置き換えてください（利用条件の確認を忘れずに）。

## 注意

- 無料の GitHub Pages は公開リポジトリが前提のため、URLを知っていれば誰でもページを見られます（中身はニュースの見出しと短い抜粋、元記事へのリンク）。
- GitHub の定期実行は、リポジトリに **60日間** 更新がないと自動停止します。停止したらメールが届くので、Actions 画面から再度有効にしてください。
- Googleニュース経由の記事は概要文が取れないことが多く、タイトルのみの読み上げになります。
- edge-tts は公式APIではないため、将来使えなくなる可能性があります。
