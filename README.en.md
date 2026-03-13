```markdown
# WordNest 🎯

Your exclusive English vocabulary handbook! (｡♥‿♥｡) A modern personal word-learning system based on Flask, designed to help you tuck away those "impossible to remember" words into a cozy nest for gradual digestion~ Featuring AI smart assistants, knowledge graph visualization, and other black technologies to turn your vocabulary nightmares into a dream! ✧(≖ ◡ ≖✿)

<div align="center">
  <img src="screenshots/LOGO.jpg" alt="WordNest Logo" width="350"/>
</div>

<div align="center">

![WordNest Logo](https://img.shields.io/badge/WordNest-✨_Build_your_own_dictionaries-ff69b4?style=for-the-badge)
[![Python](https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3.3-green?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

</div>

## 💡 Why I Built This

As someone who has been (and honestly, still is) tormented by English vocabulary, I've tried every word-learning app out there... (´･ω･`)

**However, the reality is brutal:**
- 🤢 **Counter-intuitive UI**: Either too flashy to find the focus, or just plain eyesores 😟
- 😵 **Repeating Known Words**: Constantly pushing words I've already mastered—wasting time and crushing motivation 🥺
- 📚 **Vast, Aimless Libraries**: Staring at tens of thousands of words without knowing where to start 🥹
- ⚡ **Pathetic Efficiency**: Realizing after hours of study that most of the work was repetitive, with very few actual "problem words" conquered 😭

**When I reached my breaking point, I thought:** If nothing out there works, why not build my own! (ง •̀_•́)ง

Thus, WordNest was born~ A vocabulary handbook truly focused on **YOUR specific new words**. Say goodbye to useless repetition and make every minute of study count!

**Developer**: [@wink-wink-wink555](https://github.com/wink-wink-wink555) | A college student once scarred by vocabulary apps (◕‿◕)

## ✨ Features

### 📚 Personal Vocabulary Handbook
- **Exclusive Vocabulary Base**: Only includes words you add yourself—no more wasted effort! (๑•̀ㅂ•́)و✧
- **Smart Tagging System**: Star key words to target and conquer your specific difficulties.
- **Personalized Customization**: Your library, your rules! Every word is your "old rival."

### 🤖 AI Smart Assistant
- **Smart Example Generation**: Powered by Ollama + Qwen local LLMs for instant, authentic example sentences ٩(◕‿◕)六
- **Memory Technique Assistant**: AI-generated mnemonics and study notes to make words "stick."
- **Knowledge Graph Magic**: DeepSeek API maps out vocabulary connections, revealing the mysterious links between words ✨

### 🎨 Aesthetics First
- **Responsive Design**: Smooth, sleek interface for learning anytime, anywhere (´∀｀)♡
- **Night Mode**: A lifesaver for late-night study sessions—no more blinding lights or complaints from roommates!
- **Fluid Interactions**: Silky transition animations make even switching words a joy.
- **Keyboard Shortcuts**: A paradise for power users—efficiency is at your fingertips! ⚡

### 🔒 Privacy & Security
- **Local Execution**: Your wordbook belongs to you alone; 100% privacy protection (｡◕‿◕｡)
- **Offline Access**: Learn words even without internet—never waste your subway commute.
- **Data Export**: Export to CSV for easy backups; no more fear of losing your progress.

## 📸 Product Preview

Take a look at the true face of WordNest! Every interface is built with love~ ✨

### 🎯 Word Quiz Mode
Randomly pull from your words to test your memory:

<div align="center">
<img src="screenshots/1.png" alt="Word Quiz Interface" width="600"/>
<p><em>Clean quiz interface focused on the word itself (◕‿◕)</em></p>
</div>

Click to show definitions and verify your learning:

<div align="center">
<img src="screenshots/2.png" alt="View Word Definition" width="600"/>
<p><em>Clear view of POS, definitions, and examples at a glance!</em></p>
</div>

### 📚 Personal Library Management
Full word list tracking your learning journey:

<div align="center">
<img src="screenshots/3.png" alt="Full Word List View" width="600"/>
<p><em>Full view showing definitions to review your progress.</em></p>
</div>

Compact mode for quick browsing:

<div align="center">
<img src="screenshots/4.png" alt="Compact Word List View" width="600"/>
<p><em>Compact view hiding definitions to test your recall.</em></p>
</div>

Select a word for instant details:

<div align="center">
<img src="screenshots/7.png" alt="Selected Word Details" width="600"/>
<p><em>Click a word to show details instantly—super smooth interaction~</em></p>
</div>

Edit or switch between lists anytime:

<div align="center">
<img src="screenshots/10.png" alt="Manage Word Lists" width="600"/>
<p><em>Multi-list support~ Rename, edit, or enter lists with one click!</em></p>
</div>

Create new word lists on the fly:

<div align="center">
<img src="screenshots/11.png" alt="Create Word List" width="600"/>
<p><em>Multi-list support~ Create new lists whenever you need!</em></p>
</div>

### 🕸️ AI Knowledge Graph Magic (Beta)
Vocabulary association maps drawn by DeepSeek API:

<div align="center">
<img src="screenshots/5.png" alt="Knowledge Graph Visualization" width="600"/>
<p><em>Magical knowledge graphs to discover hidden connections between words ✨</em></p>
</div>

Smart learning path suggestions:

<div align="center">
<img src="screenshots/6.png" alt="Learning Path Suggestions" width="600"/>
<p><em>AI provides thoughtful suggestions to give your learning direction.</em></p>
</div>

### ➕ Add New Words
Simple and intuitive addition interface:

<div align="center">
<img src="screenshots/8.png" alt="Add New Word Interface" width="600"/>
<p><em>Supports multiple POS and definitions, with AI one-click autofill!</em></p>
</div>

### 🌙 Night Mode
Eye-friendly dark theme:

<div align="center">
<img src="screenshots/9.png" alt="Night Mode Interface" width="600"/>
<p><em>Gentle night mode for late-night study sessions (｡♥‿♥｡)</em></p>
</div>

## 🚀 Quick Start

### Prerequisites

- Python 3.8+ (Most modern computers are already set~)
- 2GB available disk space (Give your words a warm home)
- DeepSeek API key for AI magic features ✨

### Installation Steps

1. **Bring the project home** (づ｡◕‿‿◕｡)づ
```bash
git clone [https://github.com/wink-wink-wink555/WordNest.git](https://github.com/wink-wink-wink555/WordNest.git)
cd WordNest

```

2. **Give the project its own little room**

```bash
# For Windows users ↓
python -m venv venv
venv\Scripts\activate

# For macOS/Linux users ↓
python3 -m venv venv
source venv/bin/activate

```

3. **Install necessary toolkits**

```bash
pip install -r requirements.txt

```

4. **Configure API Keys** (Required for AI features!)
The project uses `config.py` for configuration management. Edit `config.py` and replace the default values with your own:

```python
DEEPSEEK_API_KEY = 'YOUR_KEY_HERE'

```

5. **Launch your WordNest** ✨

```bash
python app.py

```

6. **Start your vocabulary journey**
Open your browser and visit: http://127.0.0.1:5000
Congratulations! Your personal word handbook is online! (ﾉ◕ヮ◕)ﾉ*:･ﾟ✧

## 📖 Usage Guide

### 📝 Your Exclusive Handbook

This isn't just another word app! It's your private word collection~ (◕‿◕)♡

**Core Philosophy**: Only record the "unknown" words you personally add. Escape the confusion of massive pre-made libraries! Every word is your "old rival"—conquer them through repeated review!

#### 🎯 Learning Modes

* 🎲 **Random Test**: Pull words randomly from your library—every session is a surprise!
* ⭐ **Star Focus**: Mark those "stubborn" words and focus your efforts.
* 📖 **View Definitions**: One-click toggle (Spacebar) to hide/show definitions and test yourself.
* ⏭️ **Infinite Switching**: Use arrow keys to quickly cycle through words—learning becomes addictive!

#### ⌨️ Shortcut Tips

* `Space`：Show/Hide definition (Most used!)
* `→`：Next word
* `←`：View word details
* `Esc`：Close popup

### 📚 Library Management

#### Word Collection

* ➕ **Add Words**: Record new words instantly when you encounter them; supports multiple POS/definitions.
* ✏️ **Refine Info**: Edit word info anytime to enrich your library.
* 🗑️ **Clean Up**: Remove words you've mastered to keep your library lean.
* 🔍 **Quick Locate**: Find target words quickly via alphabetical index.

#### 🤖 AI Learning Assistant

* 🧠 **Ollama + Qwen Generation**: Local AI tailors authentic example sentences for your words.
* 💡 **Smart Mnemonics**: AI analyzes word characteristics to provide personalized memory tips.
* 🕸️ **DeepSeek Graph**: Visually display word associations to discover learning patterns.

### 📊 Data Management

#### Backup & Sharing

* 📤 **CSV Export**: Export your library to share with friends and grow together!
* 📥 **Data Security**: Regularly backup your progress so you never fear a system reinstall.
* ⚙️ **Personalization**: Your preferences are saved; the system remembers every detail.

## 🏗️ Project Architecture

This project adopts a **modern layered architecture**, ensuring clean code that is easy to maintain and extend:

```
WordNest/
├── 📄 app.py                  # Flask Application Entry (App Factory Pattern)
├── ⚙️ config.py                # Configuration Management
├── 🗃️ models.py                # Database Model Definitions
│
├── 📁 routes/                  # 🎯 Routing Layer (Blueprints)
│   ├── __init__.py             # Route Module Initialization
│   ├── word_routes.py          # Word CRUD + Self-test Functions
│   ├── graph_routes.py         # Knowledge Graph Display
│   └── api_routes.py           # RESTful API Interfaces
│
├── 📁 services/                # 💼 Service Layer (Business Logic)
│   ├── __init__.py             # Service Module Initialization
│   ├── word_service.py         # Word Business Logic
│   ├── llm_service.py          # LLM AI Services
│   └── graph_service.py        # Knowledge Graph Services
│
├── 📁 utils/                   # 🛠️ Utility Modules
│   ├── __init__.py             # Utility Module Initialization
│   ├── constants.py            # Constant Definitions
│   └── settings.py             # Settings File Management
│
├── 📁 static/                  # 🎨 Static Assets
│   ├── style.css               # Stylesheets
│   ├── script.js               # Main Scripts
│   └── js/
│       └── vis-network.min.js   # Graph Visualization Library
│
├── 📁 templates/                # 🖼️ HTML Templates
│   ├── index.html               # Main Page (Word Quiz)
│   ├── word_list.html           # Word List
│   ├── add_word.html            # Add Word
│   ├── add_definition.html      # Add Definition
│   ├── edit_word.html           # Edit Word
│   └── knowledge_graph.html     # Knowledge Graph
│
├── 📁 instance/                # 🗄️ Database Folder
│   └── words.db                 # SQLite Database
│
├── ⚙️ settings.json            # App Settings (Generated locally)
├── 📋 settings.example.json    # Settings Template
├── 🚫 .gitignore               # Git Ignore Rules
├── 📋 requirements.txt         # Python Dependencies
└── 📖 README.md                # Project Documentation

```

### 🎯 Architecture Highlights

**Three-Tier Architecture - Separation of Concerns**

1. **Routing Layer (Routes)**
* Handles HTTP requests and responses.
* Parameter validation and error handling.
* Modular management using Flask Blueprints.


2. **Service Layer (Services)**
* Encapsulates core business logic.
* Reusable functional modules.
* Decoupled from the routing layer for improved testability.


3. **Data Layer (Models)**
* SQLAlchemy ORM data models.
* Database operation encapsulation.
* Supports switching between multiple database types.



**Design Advantages** ✨

* 📦 **Modular**: Clear responsibilities for each layer, easy to understand.
* 🔧 **Maintainable**: Logical organization minimizes the impact of changes.
* 🧪 **Testable**: Independent business logic facilitates unit testing.
* 🚀 **Extensible**: Adding new features simply requires extending the corresponding layers.

## 🔧 AI Magic Configuration

Want to unlock AI superpowers? Follow these steps to set it up~ ✨

### 🧠 Local AI Assistant Setup (Ollama + Qwen)

Let the AI live on your computer to generate custom examples and study notes:

1. **Install Ollama** (The home for local AI)

```bash
# Visit [https://ollama.com/](https://ollama.com/) to download the installer
# Install it like any regular software—just click through (◡‿◡)
   
# After installation, download the super-smart Qwen model
ollama pull qwen2.5:3b

```

2. **Configure DeepSeek API** (The Knowledge Graph Wizard)

Edit the `config.py` file and replace the default value with your key:

```python
DEEPSEEK_API_KEY = 'YOUR_KEY_HERE'

```

### Database Configuration

Uses SQLite by default, but supports other databases:

```bash
# PostgreSQL Example
DATABASE_URI=postgresql://username:password@localhost/wordnest

# MySQL Example  
DATABASE_URI=mysql://username:password@localhost/wordnest

```

### Deployment Configuration

For production deployment, use Gunicorn:

```bash
# Install gunicorn (included in requirements.txt)
pip install gunicorn

# Start the production server
gunicorn -w 4 -b 0.0.0.0:8000 app:app

```

## 🤝 Contribution Guide

Contributions to WordNest are welcome! Please follow these steps:

### Development Setup

1. **Fork this repository**
2. **Create a feature branch**
```bash
git checkout -b feature/amazing-feature

```


3. **Install development dependencies**
```bash
pip install pytest pytest-flask black flake8

```


4. **Run tests**
```bash
pytest

```


5. **Format code**
```bash
black .
flake8 .

```



### 🏗️ Architecture Development Guide

If you wish to add new features, please follow these layered architecture principles:

**1. Adding New Business Logic**

```
Step 1: Create or extend a service class in services/
Step 2: Add corresponding route handlers in routes/
Step 3: If a new page is needed, add a template in templates/
Step 4: Update config.py (if new configuration items are needed)

```

**2. Code Organization Principles**

* ✅ **Routes**: Only handle HTTP request/response; call service layer methods.
* ✅ **Services**: Contain all business logic; should be reusable.
* ✅ **Models**: Handle data models and database operations only.
* ❌ **Avoid**: Directly operating on the database within routes.
* ❌ **Avoid**: Handling HTTP request objects within the service layer.

**3. Example: Adding a "Favorite" Word Feature**

```python
# Step 1: services/word_service.py
class WordService:
    @staticmethod
    def toggle_favorite(word_str):
        # Business logic here
        pass

# Step 2: routes/word_routes.py
@word_bp.route('/favorite/<word>', methods=['POST'])
def favorite_word(word):
    if WordService.toggle_favorite(word):
        return jsonify({'success': True})
    return jsonify({'error': 'Operation failed'}), 400

```

### Commit Conventions

* 🎨 `feat:` New feature
* 🐛 `fix:` Bug fix
* 📚 `docs:` Documentation updates
* 💄 `style:` Code style/formatting
* ♻️ `refactor:` Refactoring
* ⚡ `perf:` Performance optimization
* 🔧 `chore:` Build/Tools

### Pull Requests

1. Ensure code passes all tests.
2. Update relevant documentation.
3. Provide a detailed description of changes.
4. Wait for code review.

## 🐛 Bug Reports

Encountered an issue? Feedback via:

1. **GitHub Issues**: [Submit an Issue](https://github.com/wink-wink-wink555/WordNest/issues)
2. **Feature Suggestions**: Use the `enhancement` label in Issues.
3. **Bug Reports**: Use the Issue template to provide detailed info.

## 📄 License

This project is licensed under the [MIT License](https://www.google.com/search?q=LICENSE).

## 🙏 Acknowledgements

* **Flask**: The excellent Python Web framework that makes development a joy.
* **SQLAlchemy**: Powerful ORM tool that makes database operations so easy.
* **Ollama**: Guardian of local LLMs, making AI accessible to everyone.
* **Vis.js**: Beautiful graph visualization library that makes connections visible.
* **DeepSeek**: Powerful AI engine, the hero behind the knowledge graphs.
* **All English Learners**: The inspiration for this project—to make vocabulary study painless! (ง •̀_•́)ง

## 📞 Contact Author

Want to chat? Looking to collaborate? Or just want to say "thanks"? Feel free to reach out~ (◕‿◕)♡

* **📧 Email**: [yfsun.jeff@gmail.com]()
* **🐱 GitHub**: [wink-wink-wink555](https://github.com/wink-wink-wink555)
* **💼 LinkedIn**: [Yifei Sun](https://www.linkedin.com/in/yifei-sun-0bab66341/)
* **📺 Bilibili**: [NO_Desire](https://space.bilibili.com/623490717)

## ⭐ Star History

If this project helps you, please give us a Star!

[![Star History Chart](https://api.star-history.com/svg?repos=wink-wink-wink555/WordNest&type=Date)](https://star-history.com/#wink-wink-wink555/WordNest&Date)

---

<div align="center">

**May every English learning dream shine bright ✨**

**Remember: The best wordbook is the one you build yourself!** (｡♥‿♥｡)

Made with ❤️ for everyone who has ever struggled with vocabulary.

[📖 View Docs](https://github.com/wink-wink-wink555/WordNest/wiki) | [🚀 Quick Start](https://www.google.com/search?q=%23-quick-start) | [🤝 Contribute](https://www.google.com/search?q=%23-contribution-guide)

</div>