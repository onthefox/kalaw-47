import React, { useEffect, useRef, useMemo } from "react";
import * as d3 from "d3";

export default function Graph({ nodes, links, onSelect, highlightedNodeIds }) {
  const ref = useRef();
  
  // Мемоизация данных для предотвращения лишних ре-рендеров
  const data = useMemo(() => ({ 
    nodes: [...nodes], 
    links: [...links] 
  }), [nodes, links]);

  useEffect(() => {
    if (!data.nodes.length) return;

    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();

    // Адаптивный размер
    const width = ref.current.clientWidth || 600;
    const height = ref.current.clientHeight || 400;
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    // Оптимизированная симуляция с лучшей производительностью
    const simulation = d3
      .forceSimulation(data.nodes)
      .force("link", d3.forceLink(data.links).id((d) => d.id).distance(80))
      .force("charge", d3.forceManyBody().strength(-300))  // Сильнее отталкивание
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide(20))  // Предотвращение наложений
      .alphaDecay(0.02)  // Быстрее затухание
      .alphaMin(0.1);    // Ранняя остановка

    const link = svg
      .append("g")
      .selectAll("line")
      .data(links)
      .enter()
      .append("line")
      .attr("stroke", "#555")
      .attr("stroke-width", 1.5);

    const node = svg
      .append("g")
      .selectAll("circle")
      .data(nodes)
      .enter()
      .append("circle")
      .attr("r", 18)
      .attr("fill", (d) => {
        // Подсветка найденных узлов
        if (highlightedNodeIds && highlightedNodeIds.has(d.id)) {
          return "#ffeb3b"; // Yellow for highlighted
        }
        return "#4fc3f7";
      })
      .attr("stroke", (d) => {
        if (highlightedNodeIds && highlightedNodeIds.has(d.id)) {
          return "#ff9800"; // Orange stroke for highlighted
        }
        return "#0288d1";
      })
      .attr("stroke-width", (d) => {
        if (highlightedNodeIds && highlightedNodeIds.has(d.id)) {
          return 3;  // Thicker stroke for highlighted
        }
        return 2;
      })
      .style("cursor", "pointer")
      .call(drag(simulation))
      .on("click", (event, d) => onSelect && onSelect(d));

    const label = svg
      .append("g")
      .selectAll("text")
      .data(nodes)
      .enter()
      .append("text")
      .text((d) => d.name)
      .attr("font-size", 11)
      .attr("fill", (d) => {
        if (highlightedNodeIds && highlightedNodeIds.has(d.id)) {
          return "#ffeb3b";
        }
        return "#e0e0e0";
      })
      .attr("dx", 22)
      .attr("dy", 4);

    // Ограниченное количество тиков для производительности
    simulation.on("tick", () => {
      link
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      node.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
      label.attr("x", (d) => d.x).attr("y", (d) => d.y);
    });

    // Ручная остановка после ограниченного числа итераций
    simulation.stop();
    for (let i = 0; i < 300; i++) {
      simulation.tick();
    }

    return () => simulation.stop();
  }, [data, links, nodes, onSelect, highlightedNodeIds]);

  return (
    <svg
      ref={ref}
      style={{ 
        width: "100%", 
        height: "100%", 
        background: "#111",
        borderRadius: 8,
        border: "1px solid #333"
      }}
    ></svg>
  );
}

function drag(simulation) {
  function dragstarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x;
    d.fy = d.y;
  }
  function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;
  }
  function dragended(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
  }
  return d3
    .drag()
    .on("start", dragstarted)
    .on("drag", dragged)
    .on("end", dragended);
}
