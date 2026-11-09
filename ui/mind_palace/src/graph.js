// Интерактивный d3-граф сущностей (vanilla ES module, d3 подключён глобально).
//
// Возможности (issue #18):
//  - force-раскладка с охлаждением и остановкой (60fps на 100+ узлах:
//    за тик обновляются только transform/координаты, симуляция останавливается
//    при alpha < alphaMin);
//  - зум + pan с ограничениями (scaleExtent 0.25–4, translateExtent);
//  - drag узлов с закреплением (двойной клик отпускает);
//  - подсветка поиска: совпадения подсвечены, остальное приглушено;
//  - анимации появления/удаления узлов и связей, уважает prefers-reduced-motion;
//  - клавиатура: узлы — фокусируемые кнопки (Tab/Enter/Space).

const LABEL_LIMIT = 22;

function truncateLabel(name) {
  return name.length > LABEL_LIMIT ? `${name.slice(0, LABEL_LIMIT - 1)}…` : name;
}

export class MindGraph {
  /**
   * @param {HTMLElement} container
   * @param {{onSelect?: (id: string|null) => void}} handlers
   */
  constructor(container, { onSelect = null } = {}) {
    this.container = container;
    this.onSelect = onSelect;
    this.nodes = [];
    this.links = [];
    this.highlightIds = new Set();
    this.selectedId = null;
    this.width = 0;
    this.height = 0;

    this.svg = d3
      .select(container)
      .append("svg")
      .attr("class", "graph-svg")
      .attr("role", "img")
      .attr("aria-label", "Граф сущностей");

    this.defs = this.svg.append("defs");
    this._renderFilters();
    this._renderMarkers();

    this.zoomLayer = this.svg.append("g").attr("class", "zoom-layer");
    this.linkLayer = this.zoomLayer.append("g").attr("class", "link-layer");
    this.nodeLayer = this.zoomLayer.append("g").attr("class", "node-layer");

    this.zoom = d3
      .zoom()
      .scaleExtent([0.25, 4])
      .on("zoom", (event) => {
        this.zoomLayer.attr("transform", event.transform);
      });

    this.svg.call(this.zoom).on("dblclick.zoom", null);

    this.svg.on("click", (event) => {
      if (event.target === this.svg.node() || event.target.classList.contains("zoom-layer")) {
        this.setSelected(null);
      }
    });

    this.drag = d3
      .drag()
      .on("start", (event, d) => {
        if (!event.active) this.simulation.alphaTarget(0.2).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) this.simulation.alphaTarget(0);
        // Узел остаётся закреплённым там, куда его перетащили.
      });

    this.simulation = d3
      .forceSimulation()
      .force(
        "link",
        d3.forceLink().id((d) => d.id).distance(95).strength(0.5),
      )
      .force("charge", d3.forceManyBody().strength(-280).theta(0.9))
      .force("collide", d3.forceCollide().radius((d) => this.radius(d) + 16).iterations(1))
      .force("x", d3.forceX(() => this.width / 2).strength(0.03))
      .force("y", d3.forceY(() => this.height / 2).strength(0.03))
      .alphaMin(0.02)
      .on("tick", () => this._tick());

    this._resizeObserver = new ResizeObserver(() => this._resize());
    this._resizeObserver.observe(container);
    this._resize();
  }

  _renderFilters() {
    this.defs
      .append("filter")
      .attr("id", "glow")
      .attr("x", "-60%")
      .attr("y", "-60%")
      .attr("width", "220%")
      .attr("height", "220%")
      .html(
        '<feGaussianBlur stdDeviation="3.2" result="blur"/>' +
          '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>',
      );
  }

  _renderMarkers() {
    for (const type of ["contains", "depends", "relates", "blocks", "triggers"]) {
      this.defs
        .append("marker")
        .attr("id", `arrow-${type}`)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 16)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("class", `arrow arrow-${type}`);
    }
  }

  _resize() {
    const rect = this.container.getBoundingClientRect();
    this.width = Math.max(320, rect.width);
    this.height = Math.max(240, rect.height);
    this.svg.attr("viewBox", `0 0 ${this.width} ${this.height}`).attr("width", this.width).attr("height", this.height);
    this.zoom
      .extent([
        [0, 0],
        [this.width, this.height],
      ])
      .translateExtent([
        [-this.width * 0.6, -this.height * 0.6],
        [this.width * 1.6, this.height * 1.6],
      ]);
    this.simulation.force("x").x(this.width / 2);
    this.simulation.force("y").y(this.height / 2);
  }

  radius(d) {
    return Math.min(15, 7 + (d.degree || 0) * 0.9);
  }

  /**
   * Обновление данных графа.
   * @param {{nodes: Array, links: Array, highlightIds?: Set<string>, selectedId?: string|null}} payload
   *   nodes: [{id, name, tags, priority, degree}] (id — строка)
   *   links: [{id, source, target, type}] (source/target — строки id)
   */
  update({ nodes, links, highlightIds = null, selectedId = null }) {
    const oldById = new Map(this.nodes.map((n) => [n.id, n]));
    const freshNodes = nodes.map((n) => {
      const old = oldById.get(n.id);
      return { ...n, x: old ? old.x : undefined, y: old ? old.y : undefined, fx: old ? old.fx : undefined, fy: old ? old.fy : undefined };
    });
    const freshLinks = links.map((l) => ({ id: l.id, source: String(l.source), target: String(l.target), type: l.type }));

    const structuralChange =
      freshNodes.length !== this.nodes.length ||
      freshLinks.length !== this.links.length ||
      this._idsChanged(this.nodes, freshNodes) ||
      this._idsChanged(this.links, freshLinks);

    const prevHighlight = this.highlightIds;
    const prevSelected = this.selectedId;
    this.nodes = freshNodes;
    this.links = freshLinks;
    this.nameById = new Map(freshNodes.map((n) => [n.id, n.name]));
    this.highlightIds = highlightIds || new Set();
    this.selectedId = selectedId;

    this.svg.attr(
      "aria-label",
      `Граф сущностей: ${this.nodes.length} узлов, ${this.links.length} связей`,
    );

    this._joinLinks(structuralChange);
    this._joinNodes();

    this.simulation.nodes(this.nodes);
    this.simulation.force("link").links(this.links);

    if (structuralChange) {
      this.simulation.alpha(0.7).restart();
    } else if (!this._setsEqual(prevHighlight, this.highlightIds) || prevSelected !== this.selectedId) {
      // Только подсветка — лёгкое встряхивание, чтобы анимация подсветки была заметна
      this.simulation.alpha(0.05).restart();
    }
  }

  _idsChanged(prev, next) {
    if (prev.length !== next.length) return true;
    for (let i = 0; i < prev.length; i += 1) {
      if (prev[i].id !== next[i].id) return true;
    }
    return false;
  }

  _setsEqual(a, b) {
    if (a.size !== b.size) return false;
    for (const value of a) {
      if (!b.has(value)) return false;
    }
    return true;
  }

  _joinLinks() {
    const animate = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    const self = this;
    const sel = this.linkLayer
      .selectAll("line.link")
      .data(this.links, (d) => d.id);

    sel.exit()
      .transition()
      .duration(animate ? 220 : 0)
      .style("opacity", 0)
      .remove();

    const entered = sel
      .enter()
      .append("line")
      .attr("class", (d) => `link link-${d.type}`)
      .attr("marker-end", (d) => `url(#arrow-${d.type})`);

    if (animate) {
      entered
        .style("opacity", 0)
        .transition()
        .duration(300)
        .style("opacity", 1)
        .on("end", function clearInlineOpacity() {
          d3.select(this).style("opacity", null);
        });
    }

    this.linkSel = entered
      .merge(sel)
      .attr("class", (d) => `link link-${d.type}`)
      .attr("marker-end", (d) => `url(#arrow-${d.type})`)
      .each(function assignTitle(d) {
        const label = self._linkLabel(d);
        const title = d3.select(this).select("title");
        if (title.empty()) {
          d3.select(this).append("title").text(label);
        } else {
          title.text(label);
        }
      })
      .classed("dim", (d) => this._linkDimmed(d))
      .attr("x1", (d) => (d.source && d.source.x) || 0)
      .attr("y1", (d) => (d.source && d.source.y) || 0)
      .attr("x2", (d) => (d.target && d.target.x) || 0)
      .attr("y2", (d) => (d.target && d.target.y) || 0);
  }

  _linkLabel(d) {
    const sourceId = d.source && d.source.id ? d.source.id : d.source;
    const targetId = d.target && d.target.id ? d.target.id : d.target;
    const sourceName = (this.nameById && this.nameById.get(String(sourceId))) || String(sourceId);
    const targetName = (this.nameById && this.nameById.get(String(targetId))) || String(targetId);
    return `${sourceName} — ${d.type} → ${targetName}`;
  }

  _linkDimmed(d) {
    const sourceId = d.source && d.source.id ? d.source.id : d.source;
    const targetId = d.target && d.target.id ? d.target.id : d.target;
    if (this.highlightIds.size === 0) return false;
    return !(this.highlightIds.has(String(sourceId)) || this.highlightIds.has(String(targetId)));
  }

  _joinNodes() {
    const animate = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    const self = this;

    const sel = this.nodeLayer
      .selectAll("g.node")
      .data(this.nodes, (d) => d.id);

    const exited = sel.exit();
    exited
      .transition()
      .duration(animate ? 220 : 0)
      .style("opacity", 0)
      .remove();

    const entered = sel
      .enter()
      .append("g")
      .attr("class", "node")
      .attr("tabindex", 0)
      .attr("role", "button")
      .call(this.drag)
      .on("click", (event, d) => {
        event.stopPropagation();
        if (self.onSelect) self.onSelect(d.id);
      })
      .on("keydown", (event, d) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (self.onSelect) self.onSelect(d.id);
        }
      })
      .on("dblclick", (event, d) => {
        event.stopPropagation();
        d.fx = null;
        d.fy = null;
        self.simulation.alpha(0.4).restart();
      });

    entered.append("circle").attr("r", 0);
    entered.append("text").attr("text-anchor", "middle").attr("dy", (d) => this.radius(d) + 14);

    this.nodeSel = entered.merge(sel);

    if (animate) {
      entered
        .style("opacity", 0)
        .transition()
        .duration(300)
        .style("opacity", 1)
        .on("end", function clearNodeOpacity() {
          d3.select(this).style("opacity", null);
        });
    }

    this.nodeSel
      .attr("aria-label", (d) => `Сущность ${d.name}`)
      .classed("match", (d) => this.highlightIds.has(d.id))
      .classed("dim", (d) => this.highlightIds.size > 0 && !this.highlightIds.has(d.id))
      .classed("selected", (d) => d.id === this.selectedId)
      .each(function updateNode(d) {
        const g = d3.select(this);
        const circle = g.select("circle");
        const targetR = self.radius(d);
        if (animate && Number(circle.attr("r")) === 0) {
          circle.transition().duration(320).ease(d3.easeBackOut).attr("r", targetR);
        } else {
          circle.attr("r", targetR);
        }
        g.select("text").text(truncateLabel(d.name));
        const existingTitle = g.select("title");
        if (!existingTitle.empty()) existingTitle.remove();
        g.append("title").text(
          `${d.name}${d.priority ? ` · приоритет: ${d.priority}` : ""}` +
            `${d.tags && d.tags.length ? ` · теги: ${d.tags.join(", ")}` : ""}` +
            "\nПеретащите, чтобы закрепить; двойной клик — отпустить",
        );
      });
  }

  _tick() {
    this.nodeSel.attr("transform", (d) => `translate(${d.x || 0},${d.y || 0})`);
    this.linkSel
      .attr("x1", (d) => (d.source && d.source.x) || 0)
      .attr("y1", (d) => (d.source && d.source.y) || 0)
      .attr("x2", (d) => (d.target && d.target.x) || 0)
      .attr("y2", (d) => (d.target && d.target.y) || 0);
  }

  setSelected(id) {
    if (this.selectedId === id) return;
    this.selectedId = id;
    if (this.nodeSel) {
      this.nodeSel.classed("selected", (d) => d.id === id);
    }
  }

  zoomBy(factor) {
    this.svg.transition().duration(200).call(this.zoom.scaleBy, factor);
  }

  fit(duration = 450) {
    if (!this.nodes.length) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of this.nodes) {
      if (n.x == null) continue;
      minX = Math.min(minX, n.x);
      maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y);
      maxY = Math.max(maxY, n.y);
    }
    if (!Number.isFinite(minX)) return;
    const pad = 70;
    const w = this.width - pad * 2;
    const h = this.height - pad * 2;
    const dx = Math.max(1, maxX - minX);
    const dy = Math.max(1, maxY - minY);
    const scale = Math.min(2.5, Math.max(0.25, Math.min(w / dx, h / dy)));
    const midX = (minX + maxX) / 2;
    const midY = (minY + maxY) / 2;
    const transform = d3.zoomIdentity
      .translate(this.width / 2, this.height / 2)
      .scale(scale)
      .translate(-midX, -midY);
    this.svg
      .transition()
      .duration(matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : duration)
      .call(this.zoom.transform, transform);
  }

  focusEntity(id, { select = true } = {}) {
    const node = this.nodes.find((n) => n.id === String(id));
    if (!node || node.x == null) return;
    if (select) this.setSelected(String(id));
    const transform = d3.zoomIdentity
      .translate(this.width / 2, this.height / 2)
      .scale(1.4)
      .translate(-node.x, -node.y);
    this.svg
      .transition()
      .duration(matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 420)
      .call(this.zoom.transform, transform);
  }

  destroy() {
    this._resizeObserver.disconnect();
    this.simulation.stop();
    this.svg.remove();
  }
}
