# MarkiNote ✨

<div align="center">
<img src="images/LOGO.png" alt="MarkiNote Logo" width="290"/>
</div>

<div align="center">

**強力かつ完全無料の Markdown ドキュメント管理・プレビューシステム** (｡･ω･｡)ﾉ♡

[製品プレビュー](https://www.google.com/search?q=%23-%E8%A3%BD%E5%93%81%E3%83%97%E3%83%AC%E3%83%93%E3%83%A5%E3%83%BC) • [クイックスタート](https://www.google.com/search?q=%23-%E3%82%AF%E3%82%A4%E3%83%83%E3%82%AF%E3%82%B9%E3%82%BF%E3%83%BC%E3%83%88) • [主な機能](https://www.google.com/search?q=%23-%E4%B8%BB%E3%81%AA%E6%A9%9F%E8%83%BD) • [利用ガイド](https://www.google.com/search?q=%23-%E5%88%A9%E7%94%A8%E3%82%AC%E3%82%A4%E3%83%89) • [コントリビューション](https://www.google.com/search?q=%23-%E3%82%B3%E3%83%B3%E3%83%88%E3%83%AA%E3%83%93%E3%83%A5%E3%83%BC%E3%82%B7%E3%83%A7%E3%83%B3)

</div>

---

## ✨ プロジェクト紹介

MarkiNote は、Flask をベースにしたモダンな Markdown ドキュメント管理システムです。あなたの Markdown ライフを、もっとシンプルに、もっと楽しくしちゃいます！ (★ ω ★)

### なぜ MarkiNote なの？

* 📝 **リアルタイムプレビュー**：WYSIWYG 感覚の Markdown レンダリング
* 📚 **ドキュメント管理**：ファイルマネージャーのように直感的に管理
* 🎨 **数式対応**：LaTeX 数式レンダリングを完璧にサポート
* 🌈 **美しい UI**：モダンなデザインで、使い心地バツグン
* 🚀 **軽量＆高速**：Flask ベースなので、起動が早くてリソース消費も少なめ

---

## 🎯 主な機能

### 📂 ファイル管理

* ✅ ファイル単体、またはフォルダごとのアップロード
* ✅ ファイルやフォルダの作成、削除、移動、編集
* ✅ パンくずリストで、ファイル構造をらくらく把握
* ✅ 右クリックメニューによるクイック操作

### 📝 Markdown プレビュー

* ✅ Markdown ドキュメントをリアルタイムに表示
* ✅ GFM (GitHub Flavored Markdown) をサポート
* ✅ コードハイライト表示
* ✅ テーブル、リスト、引用などのフルサポート
* ✅ 数式レンダリング (MathJax)
* ✅ Markdown ソースコードの表示・編集
* ✅ Mermaid チャート対応

---

## 📸 製品プレビュー

**MarkiNote の素顔を見てみましょう！どの画面も愛情たっぷりです〜** ✨

<div align="center">
<img src="images/1.png" alt="サンプル1" width="600"/>
<p><em>コンテンツ閲覧からファイル管理まで、操作感はとってもスムーズ</em></p>
</div>

<div align="center">
<img src="images/2.png" alt="サンプル2" width="600"/>
<p><em>LaTex 数式やコードブロックのレンダリングもバッチリ</em></p>
</div>

<div align="center">
<img src="images/3.png" alt="サンプル3" width="600"/>
<p><em>Mermaid による各種チャート作成もサポート</em></p>
</div>

<div align="center">
<img src="images/4.png" alt="サンプル4" width="600"/>
<p><em>ファイルが増えても大丈夫！キーワード検索で一発解決</em></p>
</div>

<div align="center">
<img src="images/5.png" alt="サンプル5" width="600"/>
<p><em>夜中にこっそり作業したい？そんな時はダークモードに切り替え！</em></p>
</div>

<div align="center">
<img src="images/6.png" alt="サンプル6" width="600"/>
<p><em>ソースコードの確認・編集もワンクリック。効率爆上がりです！</em></p>
</div>

---

## 🚀 クイックスタート

### 環境要件

* Python 3.8 以上
* pip パッケージマネージャー

### インストール手順

1️⃣ **プロジェクトをクローン**

```bash
git clone https://github.com/wink-wink-wink555/MarkiNote.git
cd MarkiNote

```

2️⃣ **依存関係のインストール**

```bash
pip install -r requirements.txt

```

3️⃣ **フロントエンドライブラリのダウンロード**

プロジェクトではローカルのフロントエンドライブラリ（MathJax、Mermaid、html2canvas）を使用しており、`static/libs/` フォルダに含まれています。更新が必要な場合は、以下を実行してください：

```bash
# Windows PowerShell
Invoke-WebRequest -Uri "https://unpkg.com/mathjax@3.2.2/es5/tex-mml-chtml.js" -OutFile "static/libs/tex-mml-chtml.js"
Invoke-WebRequest -Uri "https://unpkg.com/mermaid@10/dist/mermaid.min.js" -OutFile "static/libs/mermaid.min.js"
Invoke-WebRequest -Uri "https://unpkg.com/html2canvas@1.4.1/dist/html2canvas.min.js" -OutFile "static/libs/html2canvas.min.js"

# Linux/Mac
curl -L -o static/libs/tex-mml-chtml.js "https://unpkg.com/mathjax@3.2.2/es5/tex-mml-chtml.js"
curl -L -o static/libs/mermaid.min.js "https://unpkg.com/mermaid@10/dist/mermaid.min.js"
curl -L -o static/libs/html2canvas.min.js "https://unpkg.com/html2canvas@1.4.1/dist/html2canvas.min.js"

```

4️⃣ **アプリを起動**

```bash
python main.py

```

5️⃣ **ブラウザで開く**

`http://localhost:5000` にアクセスして、さっそく使い始めましょう！ ヾ(≧▽≦*)o

---

## 📖 利用ガイド

### 基本操作

1. **ファイルをアップロード** (｡･ω･｡)ﾉ♡
* サイドバーの「アップロード」ボタンをクリック
* ファイルまたはフォルダを選択
* `.md`、`.markdown`、`.txt` 形式をサポートしています


2. **ドキュメントをプレビュー** ✨
* 左側のファイルリストからファイルをクリック
* 右側にレンダリングされた内容がリアルタイムで表示されます
* 「ソースを表示」をクリックすると、生の Markdown を確認できます


3. **ファイルを管理** 📁
* ファイル/フォルダを右クリックしてメニューを表示
* プレビュー、移動、削除などの操作が可能です
* 「新規フォルダ」ボタンで新しいフォルダを作成できます



### アドバンスド機能

* **数式**：インライン数式 `$ ... $` とブロック数式 `$$...$$` に対応
* **コードハイライト**：````言語名` を使ってコードブロックを作成
* **Mermaid チャート**：フローチャートやシーケンス図などの可視化に対応

詳細な使い方は、 [lib/新手指南.md](https://www.google.com/search?q=lib/%E6%96%B0%E6%89%8B%E6%8C%87%E5%8D%97.md) をご覧ください (｡♥‿♥｡)

---

## 📁 プロジェクト構造

```
MarkiNote/
├── app/                    # Flask アプリコア
│   ├── __init__.py         # アプリ初期化
│   ├── config.py           # 設定ファイル
│   ├── routes/             # ルーティングモジュール
│   │   ├── main_routes.py     # メインルーティング
│   │   └── library_routes.py  # ファイル管理ルーティング
│   └── utils/              # ユーティリティ関数
│       ├── file_utils.py      # ファイル処理
│       └── markdown_utils.py  # Markdown レンダリング
├── static/                 # 静的リソース
│   ├── libs/               # フロントエンドライブラリ（ローカル）
│   │   ├── tex-mml-chtml.js      # MathJax
│   │   ├── mermaid.min.js        # Mermaid
│   │   └── html2canvas.min.js    # html2canvas
│   ├── style.css           # スタイルシート
│   └── script.js           # フロントエンドスクリプト
├── templates/              # HTML テンプレート
│   └── index.html
├── lib/                    # ドキュメントライブラリ（Markdown 格納先）
├── main.py                 # アプリのエントリーポイント
├── requirements.txt        # 依存関係リスト
└── README.md               # プロジェクト説明書

```

---

## 🛠️ 技術スタック

### バックエンド

* **Flask 3.0.0** - Web フレームワーク
* **markdown** - Markdown 解析
* **BeautifulSoup4** - HTML 処理
* **Pygments** - コード構文ハイライト

### フロントエンド

* **Vanilla JavaScript** - 純粋な JS（フレームワーク依存なし）
* **MathJax 3** - 数式レンダリング
* **Mermaid** - チャートレンダリング
* **html2canvas** - スクリーンショット機能

---

## 🤝 コントリビューション

あらゆる形での貢献を歓迎します！(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧

### 貢献方法

1. このプロジェクトを Fork する
2. フィーチャーブランチを作成する (`git checkout -b feature/AmazingFeature`)
3. 変更内容をコミットする (`git commit -m 'Add some AmazingFeature'`)
4. ブランチにプッシュする (`git push origin feature/AmazingFeature`)
5. Pull Request を作成する

### 問題の報告

バグを見つけたり、新機能の提案がある場合は、 [Issues](https://github.com/wink-wink-wink555/MarkiNote/issues) で教えてください！

---

## 📄 ライセンス

このプロジェクトは MIT ライセンスの下で公開されています。詳細は [LICENSE](https://www.google.com/search?q=LICENSE) ファイルをご覧ください。

---

## 💖 謝辞

このプロジェクトに貢献してくれたすべての開発者に感謝します！ (づ｡◕‿‿◕｡)づ

特に以下のオープンソースプロジェクトに感謝いたします：

* [Flask](https://flask.palletsprojects.com/)
* [MathJax](https://www.mathjax.org/)
* [Mermaid](https://mermaid.js.org/)

---

<div align="center">

<p><strong>Made with ❤️ by <a href="https://github.com/wink-wink-wink555">wink-wink-wink555</a></strong></p>

<p>このプロジェクトがお役に立てたら、ぜひ ⭐️ で応援してくださいね！ (◕‿◕✿)</p>

</div>