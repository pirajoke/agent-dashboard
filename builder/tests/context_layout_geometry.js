/* Rendered context layout regression; no browser launch, network or mutations.
 * Run this function via CUA DOM evaluation at viewport widths 1280, 832, 390,
 * once with the list visible and once after selecting a record. A minimum of
 * 98% available width allows fractional pixels/borders, not an empty column.
 * RED observed before fix: width832, layout560, list260 => ratio0.4642857143.
 * Assertions inspect actual geometry, without depending on grid/CSS choices.
 */
function assertContextLayoutGeometry() {
  const layout = document.querySelector('.context-layout');
  const list = document.getElementById('context-list');
  const reader = document.getElementById('context-reader');
  if (!layout || !list || !reader) throw new Error('Context layout is unavailable');
  const mode = reader.hidden ? 'list' : 'reader';
  const active = mode === 'list' ? list : reader;
  const container = layout.getBoundingClientRect();
  const box = active.getBoundingClientRect();
  const computed = getComputedStyle(layout);
  const inset = key => Number.parseFloat(computed[key]) || 0;
  const left = container.left + inset('borderLeftWidth') + inset('paddingLeft');
  const top = container.top + inset('borderTopWidth') + inset('paddingTop');
  const width = container.width - inset('borderLeftWidth') - inset('borderRightWidth') -
    inset('paddingLeft') - inset('paddingRight');
  const measurements = {
    viewport: window.innerWidth,
    mode,
    availableWidth: width,
    activeWidth: box.width,
    widthRatio: width > 0 ? box.width / width : 0,
    leftOffset: box.left - left,
    topOffset: box.top - top,
    documentOverflow: document.documentElement.scrollWidth - window.innerWidth
  };
  const violations = [];
  if (width <= 0 || box.height <= 0) violations.push('active view must be rendered');
  if (measurements.widthRatio < 0.98) violations.push('active view leaves unused horizontal space');
  if (box.width > width + 2) violations.push('active view overflows its container');
  if (Math.abs(measurements.leftOffset) > 2) violations.push('active view does not start at content edge');
  if (Math.abs(measurements.topOffset) > 2) violations.push('empty sibling leaves a blank row above active view');
  if (measurements.documentOverflow > 2) violations.push('page overflows viewport');
  if (violations.length) throw new Error(JSON.stringify({violations, measurements}));
  return {pass: true, ...measurements};
}

if (typeof module !== 'undefined') module.exports = assertContextLayoutGeometry;
