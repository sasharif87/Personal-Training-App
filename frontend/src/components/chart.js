/* frontend/src/components/chart.js */

const PHASE_COLORS = {
  Base:     '#4f7cff',
  Build:    '#f5a623',
  Peak:     '#ff4f9a',
  Taper:    '#3dd68c',
  Recovery: '#7b7f9e',
};

/**
 * Render a weekly TSS arc as an inline SVG bar chart.
 * @param {Array} arc  - array of { week, target_tss, phase, is_recovery_week, start_date }
 * @param {Object} opts - { height }
 * @returns SVG string
 */
export function tssBarChart(arc, { height = 180 } = {}) {
  if (!arc || arc.length === 0) {
    return '<p style="color:var(--text-dim);padding:20px 0">No arc data — add an A-race in the Planner.</p>';
  }

  // Fixed SVG coordinate space — all values are in these units
  const VW     = 600;
  const VH     = height;
  const pad    = { top: 16, bottom: 28, left: 36, right: 8 };
  const chartW = VW - pad.left - pad.right;
  const chartH = VH - pad.top - pad.bottom;
  const maxTSS = Math.max(...arc.map(w => w.target_tss), 1);

  const slotW  = chartW / arc.length;
  const barW   = slotW * 0.68;
  const barOff = slotW * 0.16; // left padding within slot

  const bars = arc.map((week, i) => {
    const x      = pad.left + i * slotW + barOff;
    const barH   = Math.max(2, (week.target_tss / maxTSS) * chartH);
    const y      = pad.top + (chartH - barH);
    const color  = PHASE_COLORS[week.phase] || '#4f7cff';
    const opacity = week.is_recovery_week ? 0.35 : 0.82;
    const showLabel = (i % 4 === 0 || i === arc.length - 1);
    const label  = showLabel
      ? `<text x="${x + barW / 2}" y="${VH - 6}" text-anchor="middle" fill="var(--text-muted)" font-size="11">W${week.week}</text>`
      : '';

    return `
      <rect x="${x}" y="${y}" width="${barW}" height="${barH}"
            fill="${color}" opacity="${opacity}" rx="2">
        <title>Week ${week.week} (${week.start_date}): ${week.target_tss} TSS — ${week.phase}${week.is_recovery_week ? ' recovery' : ''}</title>
      </rect>
      ${label}`;
  }).join('');

  // Horizontal grid lines at 25%, 50%, 75%
  const gridLines = [0.25, 0.5, 0.75].map(frac => {
    const ly  = pad.top + chartH * (1 - frac);
    const tss = Math.round(maxTSS * frac);
    return `
      <line x1="${pad.left}" y1="${ly}" x2="${VW - pad.right}" y2="${ly}"
            stroke="var(--border)" stroke-dasharray="3 3"/>
      <text x="${pad.left - 4}" y="${ly + 4}" text-anchor="end"
            fill="var(--text-muted)" font-size="11">${tss}</text>`;
  }).join('');

  return `
    <svg viewBox="0 0 ${VW} ${VH}" preserveAspectRatio="xMidYMid meet"
         style="width:100%;height:${height}px">
      ${gridLines}
      ${bars}
    </svg>`;
}
