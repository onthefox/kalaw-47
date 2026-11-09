# Демо MindPalace UI — сценарий записи GIF (15–30 сек)

> **Важно:** сам GIF записывается вручную (screen recording). Этот документ — готовый
> пошаговый сценарий и репетиционный путь, чтобы запись заняла одну попытку.

## Что показываем

Создание сущностей → связывание → интерактивный граф: появление узлов с анимацией,
карточка сущности со связями и timeline истории, поиск с подсветкой, drag узлов,
зум, фильтры, переключение тёмной/светлой темы.

---

## Шаг 1: Подготовка (~2 минуты, до записи)

### Вариант A — полный стек (рекомендуется)

```bash
# терминал 1: backend (FastAPI)
uvicorn backend.main:app --reload --port 8000

# терминал 2: статика UI
cd ui/mind_palace
python -m http.server 3000
```

Откройте http://localhost:3000 — UI по умолчанию стучится в `http://localhost:8000`.
Другой адрес можно задать без правки кода:

- query-параметром: `http://localhost:3000/?api=http://localhost:9000`
- глобальной переменной до загрузки модулей: `window.KALAW_API_URL = "..."`

Интернет для работы UI не нужен: d3 закоммичен локально (`ui/mind_palace/vendor/d3.min.js`).

### Вариант B — наполнить данные заранее через cURL (вместо ввода в UI)

Windows PowerShell (обратите внимание: именно `curl.exe`, не алиас `curl`):

```powershell
curl.exe -X POST http://localhost:8000/entity -H "Content-Type: application/json" -d '{\"name\": \"грядка\"}'
curl.exe -X POST http://localhost:8000/entity -H "Content-Type: application/json" -d '{\"name\": \"помидор\"}'
curl.exe -X POST http://localhost:8000/link -H "Content-Type: application/json" -d '{\"source\": \"грядка\", \"target\": \"помидор\", \"type\": \"contains\"}'
```

bash/macOS/Linux:

```bash
curl -s -X POST http://localhost:8000/entity -H 'Content-Type: application/json' -d '{"name": "грядка"}'
curl -s -X POST http://localhost:8000/entity -H 'Content-Type: application/json' -d '{"name": "помидор"}'
curl -s -X POST http://localhost:8000/link   -H 'Content-Type: application/json' -d '{"source": "грядка", "target": "помидор", "type": "contains"}'
```

Эквивалент через intent-движок (rule-based парсер понимает русский текст):

```bash
curl -s -X POST http://localhost:8000/intent -H 'Content-Type: application/json' -d '{"intent": "создать грядка"}'
curl -s -X POST http://localhost:8000/intent -H 'Content-Type: application/json' -d '{"intent": "создать помидор"}'
curl -s -X POST http://localhost:8000/intent -H 'Content-Type: application/json' -d '{"intent": "связать грядка и помидор"}'
```

Проверка данных: `curl -s http://localhost:8000/stats`

### Чистое состояние

Если сущности уже есть — удалите лишние через карточку («Удалить») или начните запись
с существующим небольшим графом.

Репетиция scripted demo path (выполните один раз до записи, чтобы проверить реакцию UI):

1. Намерение: `создать грядка` → Enter
2. Намерение: `создать помидор` → Enter
3. Клик по узлу «грядка» → карточка → кнопка «Связать» → выбрать «помидор» → «Связать»
4. Поиск: `пом` → подсветка найденного, остальные узлы приглушены
5. Перетащить узел; зум колесом; кнопки +/−/⌂
6. Фильтр по тегу/типу и переключение темы ☀️/🌙

Если всё отработало — можно записывать.

---

## Шаг 2: Раскадровка (суммарно 25–30 сек)

| # | Время | Действие | Что видит зритель |
|---|-------|----------|-------------------|
| 1 | 0:00–0:03 | Пустой граф, курсор в поле «Намерение» | Чистый экран, подсказка «создать грядка» |
| 2 | 0:03–0:08 | `создать грядка` → Enter, затем `создать помидор` → Enter | Два узла плавно появляются, ответ движка под формой |
| 3 | 0:08–0:15 | Клик по «грядка» → карточка → «Связать» → цель «помидор», тип «contains» → «Связать» | Карточка: связи, timeline истории; между узлами появляется связь |
| 4 | 0:15–0:20 | Поиск «пом», затем очистить | Совпадение подсвечено, остальные узлы приглушены |
| 5 | 0:20–0:25 | Перетащить узел, зум колесом, кнопка ⌂ (fit) | Drag с закреплением, плавный зум, автоподгонка |
| 6 | 0:25–0:30 | Переключить тему ☀️/🌙 | Плавная смена темы всего UI |

Совет: окно браузера ~1280×800, лишние вкладки закрыты, системные уведомления выключены.

### Запасной вариант на 15 секунд

Кадры 1–3 + финальный общий план графа (кнопка ⌂). Этого достаточно для README.

---

## Шаг 3: Запись

### Windows (основная платформа проекта)

- **ShareX** (бесплатно): Screen record → выбрать область окна браузера → Gif
- **OBS Studio**: запись в MP4 → конвертация в GIF на шаге 4
- **Win+G** (Xbox Game Bar): быстрое видео без установки

### macOS

```bash
brew install licecap   # GIF сразу
brew install --cask kap # видео → GIF
```

### Linux

```bash
sudo apt install peek
byzanz-record --duration=30 --delay=2 demo.gif
```

Настройки: 10–15 fps, область = окно MindPalace, без курсора-увеличителя.

---

## Шаг 4: Оптимизация

```bash
gifsicle -O3 --colors 128 --delay=8 demo.gif -o demo-optimized.gif
ffmpeg -i demo.mp4 -vf "fps=12,scale=900:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" demo.gif
```

Цель: **< 2 МБ**, 10–15 fps. Онлайн-альтернатива: https://ezgif.com/optimize

---

## Шаг 5: Публикация

1. Загрузите GIF в раздел Files issue #8 (или в imgur/github user-assets)
2. Вставьте в README:

```markdown
![MindPalace Demo](https://user-images.githubusercontent.com/USER/REPO/demo.gif)
```

3. Отметьте issue #8 комментарием со ссылкой.

---

## Альтернатива: скриншоты

Если GIF не вариант, минимальный набор из 3 скриншотов:

1. Граф с 2+ узлами и связью (тёмная тема)
2. Карточка сущности: связи + timeline истории
3. Граф с подсветкой поиска и панелью фильтров

Windows: `Win+Shift+S`. macOS: `Cmd+Shift+4`.
