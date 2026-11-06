import numpy as np

def calculate_priorities(objectives, current_scores, importance, recent_difficulty):
    dims = list(objectives)
    targets = np.array([objectives[d] for d in dims], float)
    current = np.array([current_scores[d] for d in dims], float)
    imp = np.array([importance[d] for d in dims], float)
    diff = np.array([recent_difficulty[d] for d in dims], float)
    gaps = np.maximum(0, targets - current) / 100.0
    priorities = 0.60 * gaps + 0.25 * imp + 0.15 * diff
    return {d: {'target_score': float(t), 'current_score': float(c), 'gap': float(g*100), 'priority': float(p)}
            for d, t, c, g, p in zip(dims, targets, current, gaps, priorities)}

def allocate_sessions(priorities, total_sessions):
    dims = list(priorities)
    if not dims: return {}
    weights = np.array([priorities[d]['priority'] for d in dims], float)
    if weights.sum() <= 0: weights = np.ones(len(dims), float)
    quotas = total_sessions * weights / weights.sum()
    allocation = np.floor(quotas).astype(int)
    remaining = total_sessions - int(allocation.sum())
    order = np.argsort(-(quotas-allocation), kind='stable')
    for i in order[:remaining]: allocation[i] += 1
    return dict(zip(dims, allocation.tolist()))


def generate_weekly_plan(objectives, current_scores, importance, recent_difficulty, total_sessions=7, session_minutes=20, unevaluated=None):
    unevaluated = set(unevaluated or [])
    priorities = calculate_priorities(objectives, current_scores, importance, recent_difficulty)
    allocations = allocate_sessions(priorities, total_sessions)
    measured = [d for d in priorities if d not in unevaluated]
    focus_dimension = min(measured, key=lambda d: current_scores[d]) if measured else None
    maintenance_candidates = [d for d in measured if d != focus_dimension]
    maintenance_dimension = max(maintenance_candidates, key=lambda d: current_scores[d]) if maintenance_candidates else None
    protected_dimensions = set()
    for required_dimension in (focus_dimension, maintenance_dimension):
        if required_dimension and total_sessions > 0 and allocations[required_dimension] == 0:
            donors = [d for d in allocations if d != required_dimension and
                      allocations[d] > (1 if d in protected_dimensions else 0)]
            if donors:
                donor = max(donors, key=lambda d: allocations[d])
                allocations[donor] -= 1
                allocations[required_dimension] += 1
        if required_dimension and allocations[required_dimension] > 0:
            protected_dimensions.add(required_dimension)

    plan = []
    for dim, data in priorities.items():
        if dim in unevaluated:
            role = 'baseline'
            note = 'Provisional score: play this activity to establish a baseline.'
        elif dim == maintenance_dimension:
            role = 'maintenance'
            note = 'Maintenance: keep this stronger measured skill active with regular practice.'
        elif dim == focus_dimension and data['gap'] > 0:
            role = 'focus'
            note = 'Focus: this is currently your lowest measured score; practice it and review the gap to target.'
        elif data['gap'] <= 0:
            role = 'maintenance'
            note = 'Target reached: use practice to maintain the skill and check progress.'
        elif data['gap'] >= 20:
            role = 'focus'
            note = 'Focus: this dimension has a large gap to its target.'
        else:
            role = 'practice'
            note = 'Practice regularly and review the next score against its target.'
        plan.append({'dimension': dim, **data, 'sessions': int(allocations[dim]),
                     'session_minutes': int(session_minutes), 'role': role,
                     'evaluated': dim not in unevaluated, 'note': note})
    return sorted(plan, key=lambda r: r['priority'], reverse=True)
