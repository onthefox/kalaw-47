// Карточка сущности (#19): детали, связи, таймлайн событий и действия.
// Все мутации идут через те же механизмы, что и командная строка:
//   POST /intent («переименовать X в Y», «добавить тег T к X», …)
//   POST /link   ({source, target, type})
// Модуль не знает про остальное приложение — получает контекст при open().

const LINK_TYPES = ["contains", "depends", "relates", "blocks", "triggers"];

const LINK_LABELS = {
  contains: "содержит",
  depends: "зависит от",
  relates: "связано",
  blocks: "блокирует",
  triggers: "запускает",
};

function fmtDate(ts) {
  if (ts == null) return "неизвестно";
  const d = new Date(ts * 1000);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export class EntityCard {
  /**
   * @param {HTMLElement} container — позиционируемый родитель (graph-region)
   * @param {{onNavigate?: (id: string) => void}} [opts]
   */
  constructor(container, opts = {}) {
    this.container = container;
    this.onNavigate = opts.onNavigate || (() => {});
    this.entity = null;
    this.eventsLoader = null;

    this.card = document.createElement("aside");
    this.card.className = "entity-card";
    this.card.hidden = true;
    this.card.setAttribute("aria-label", "Карточка сущности");
    this.container.appendChild(this.card);

    this.card.addEventListener("click", (event) => {
      const target = event.target.closest("[data-entity-id]");
      if (target) {
        event.stopPropagation();
        this.onNavigate(target.dataset.entityId);
      }
    });
  }

  /** Открыть карточку. context описывает сущность и способы мутировать её. */
  open(context) {
    this.entity = context.entity;
    this.eventsLoader = context.eventsLoader || null;
    this.render(context);
    this.card.hidden = false;
  }

  close() {
    this.card.hidden = true;
    this.entity = null;
    this.eventsLoader = null;
  }

  isOpen() {
    return !this.card.hidden;
  }

  get entityId() {
    return this.entity ? String(this.entity.id) : null;
  }

  // --- Отрисовка ---

  render(context) {
    const { entity, links = [], nameById = new Map(), createdTs = null, actions } = context;
    this.actions = actions || {};

    const outgoing = links.filter((l) => String(l.source_id) === String(entity.id));
    const incoming = links.filter((l) => String(l.target_id) === String(entity.id));

    this.card.replaceChildren(
      this._head(entity),
      this._body(entity, { createdTs, outgoing, incoming, nameById }),
      this._actions(entity),
    );

    // Таймлайн загружаем асинхронно, чтобы не блокировать открытие карточки.
    if (this.eventsLoader) {
      const placeholder = this.card.querySelector("[data-timeline]");
      this.eventsLoader()
        .then((events) => {
          if (this.entityId !== String(entity.id)) return;
          const holder = this.card.querySelector("[data-timeline]");
          if (holder) holder.replaceChildren(this._timeline(events));
        })
        .catch(() => {
          const holder = this.card.querySelector("[data-timeline]");
          if (holder) holder.replaceChildren(this._emptyLine("История недоступна"));
        });
      if (placeholder) placeholder.replaceChildren(this._emptyLine("Загрузка…"));
    }
  }

  _head(entity) {
    const head = document.createElement("div");
    head.className = "entity-card-head";

    const title = document.createElement("h2");
    title.textContent = entity.name;
    const id = document.createElement("div");
    id.className = "entity-card-id";
    id.textContent = `id ${entity.id}`;

    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn btn-icon entity-card-close";
    close.textContent = "✕";
    close.setAttribute("aria-label", "Закрыть карточку");
    close.addEventListener("click", () => this.close());

    const wrap = document.createElement("div");
    wrap.append(title, id);
    head.append(wrap, close);
    return head;
  }

  _body(entity, { createdTs, outgoing, incoming, nameById }) {
    const body = document.createElement("div");
    body.className = "entity-card-body";

    const meta = this._section("Метаданные");
    if (entity.priority) {
      meta.appendChild(this._chipStatic(entity.priority, `priority-${entity.priority}`));
    }
    const created = document.createElement("p");
    created.className = "meta-line";
    created.textContent = `Создана: ${fmtDate(createdTs)}`;
    meta.appendChild(created);
    if (Array.isArray(entity.tags) && entity.tags.length) {
      for (const tag of entity.tags) meta.appendChild(this._chipStatic(`#${tag}`));
    } else {
      meta.appendChild(this._emptyLine("Тегов пока нет"));
    }
    body.appendChild(meta);

    const connections = this._section("Связи");
    if (!outgoing.length && !incoming.length) {
      connections.appendChild(this._emptyLine("Связей нет — создайте через «Связать»"));
    } else {
      const list = document.createElement("ul");
      list.className = "link-list";
      for (const link of outgoing) {
        list.appendChild(this._linkItem(link.type, "→", String(link.target_id), nameById));
      }
      for (const link of incoming) {
        list.appendChild(this._linkItem(link.type, "←", String(link.source_id), nameById));
      }
      connections.appendChild(list);
    }
    body.appendChild(connections);

    const history = this._section("История");
    const timeline = document.createElement("div");
    timeline.setAttribute("data-timeline", "");
    history.appendChild(timeline);
    body.appendChild(history);

    return body;
  }

  _section(title) {
    const section = document.createElement("div");
    section.className = "entity-card-section";
    const h = document.createElement("h3");
    h.textContent = title;
    section.appendChild(h);
    return section;
  }

  _chipStatic(text, extraClass = "") {
    const chip = document.createElement("span");
    chip.className = `chip-static${extraClass ? ` ${extraClass}` : ""}`;
    chip.textContent = text;
    return chip;
  }

  _emptyLine(text) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = text;
    return p;
  }

  _linkItem(type, direction, otherId, nameById) {
    const item = document.createElement("li");
    item.className = "link-item";

    const badge = document.createElement("span");
    badge.className = `link-type-badge ${type}`;
    badge.textContent = LINK_LABELS[type] || type;

    const target = document.createElement("button");
    target.type = "button";
    target.className = "link-target";
    target.dataset.entityId = otherId;
    target.textContent = `${direction} ${nameById.get(otherId) || `id ${otherId}`}`;

    item.append(badge, target);
    return item;
  }

  _timeline(events) {
    if (!events || !events.length) return this._emptyLine("Событий пока нет");
    const list = document.createElement("ul");
    list.className = "timeline";
    for (const ev of events) {
      const item = document.createElement("li");
      item.className = `timeline-item t-${ev.type || "unknown"}`;
      const dot = document.createElement("span");
      dot.className = "timeline-dot";
      const type = document.createElement("div");
      type.className = "timeline-type";
      type.textContent = ev.type || "—";
      const time = document.createElement("div");
      time.className = "timeline-time";
      time.textContent = fmtDate(ev.ts);
      item.append(dot, type, time);
      if (ev.data != null) {
        const detail = document.createElement("div");
        detail.className = "timeline-detail";
        detail.textContent =
          typeof ev.data === "string" ? ev.data : JSON.stringify(ev.data);
        item.appendChild(detail);
      }
      list.appendChild(item);
    }
    return list;
  }

  // --- Действия ---

  _actions(entity) {
    const bar = document.createElement("div");
    bar.className = "entity-card-actions";

    const add = (label, handler, extraClass = "") => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `btn${extraClass ? ` ${extraClass}` : ""}`;
      btn.textContent = label;
      btn.addEventListener("click", () => handler());
      bar.appendChild(btn);
      return btn;
    };

    add("Переименовать", () => this._renameDialog(entity));
    add("Тег", () => this._tagDialog(entity));
    add("▲ приоритет", () => this._priority(entity, "raise"));
    add("▼ приоритет", () => this._priority(entity, "lower"));
    add("Связать", () => this._linkDialog(entity));
    add("Удалить", () => this._deleteDialog(entity), "btn-danger");

    return bar;
  }

  async _runAction(promiseFactory) {
    if (!this.actions.run) return;
    await this.actions.run(promiseFactory);
  }

  _renameDialog(entity) {
    this._dialog("Переименовать сущность", (form) => {
      const input = document.createElement("input");
      input.name = "name";
      input.required = true;
      input.value = entity.name;
      form.append(this._label("Новое имя", input));
      return async (data) => {
        const name = data.get("name").trim();
        if (name && name !== entity.name) {
          await this._runAction(() => this.actions.onRename(entity.name, name));
        }
      };
    });
  }

  _tagDialog(entity) {
    this._dialog("Добавить тег", (form) => {
      const input = document.createElement("input");
      input.name = "tag";
      input.required = true;
      input.placeholder = "важное";
      form.append(this._label("Тег", input));
      return async (data) => {
        const tag = data.get("tag").trim();
        if (tag) await this._runAction(() => this.actions.onAddTag(entity.name, tag));
      };
    });
  }

  _linkDialog(entity) {
    this._dialog("Создать связь", (form) => {
      const type = document.createElement("select");
      type.name = "type";
      for (const t of LINK_TYPES) {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = LINK_LABELS[t];
        type.appendChild(opt);
      }
      const target = document.createElement("select");
      target.name = "target";
      const entities = (this.actions.entitiesProvider && this.actions.entitiesProvider()) || [];
      const others = entities.filter((e) => String(e.id) !== String(entity.id));
      for (const e of others) {
        const opt = document.createElement("option");
        opt.value = e.name;
        opt.textContent = e.name;
        target.appendChild(opt);
      }
      form.append(this._label("Тип связи", type), this._label("С чем связать", target));
      return async (data) => {
        if (!data.get("target")) return;
        await this._runAction(() =>
          this.actions.onLink(entity.name, data.get("target"), data.get("type")),
        );
      };
    });
  }

  _priority(entity, direction) {
    this._runAction(() => this.actions.onPriority(entity.name, direction));
  }

  _deleteDialog(entity) {
    this._dialog(`Удалить «${entity.name}»?`, (form) => {
      const note = document.createElement("p");
      note.className = "muted";
      note.textContent = "Сущность будет удалена вместе с иерархической связью.";
      form.appendChild(note);
      return async () => {
        await this._runAction(() => this.actions.onDelete(entity.name));
      };
    }, true);
  }

  /** Простой confirm-стиль диалога на нативном <dialog>. */
  _dialog(title, buildFields, danger = false) {
    const dialog = document.createElement("dialog");
    const h = document.createElement("h3");
    h.textContent = title;
    const form = document.createElement("form");
    const actions = document.createElement("div");
    actions.className = "dialog-actions";

    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn btn-ghost";
    cancel.textContent = "Отмена";
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    submit.textContent = danger ? "Удалить" : "Применить";
    actions.append(cancel, submit);

    const fieldBuilder = buildFields(form);
    form.append(actions);
    dialog.append(h, form);
    document.body.appendChild(dialog);

    dialog.addEventListener("close", () => dialog.remove());
    cancel.addEventListener("click", () => dialog.close());
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      submit.disabled = true;
      try {
        await fieldBuilder(data);
        dialog.close();
      } catch (err) {
        submit.disabled = false;
        if (this.actions.onError) this.actions.onError(err);
        else throw err;
      }
    });
    dialog.showModal();
    const firstInput = form.querySelector("input");
    if (firstInput) firstInput.focus();
  }

  _label(text, control) {
    const label = document.createElement("label");
    label.append(document.createTextNode(text), control);
    return label;
  }
}
