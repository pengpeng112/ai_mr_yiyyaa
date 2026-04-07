export function createLineSeries(name, data, color) {
  return {
    name,
    type: 'line',
    data,
    smooth: true,
    itemStyle: { color },
  };
}
