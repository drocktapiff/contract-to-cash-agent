export const personas = {
  maya: { name: 'Maya Tremblay', role: 'Revenue Operations Specialist', level: 'Operational' },
  sarah: { name: 'Sarah Chen', role: 'Director of Revenue Operations', level: 'Management' },
  robert: { name: 'Robert Mitchell', role: 'Chief Financial Officer', level: 'Executive' },
};
export const normalizePersona = (value) => (Object.hasOwn(personas, value) ? value : 'maya');
