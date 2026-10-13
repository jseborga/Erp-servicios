# Part of ERP Servicios Spa. License LGPL-3.
"""Verificación de la demo instalada. Uso: odoo shell -c <conf> -d <base> < verify_shell.py

Solo lee (termina con rollback). Imprime una línea OK/FAIL por control y «RESULT OK|FAIL».
"""
env.invalidate_all()  # noqa: F821 - «env» lo define odoo shell
ok = True


def check(label, condition, detail=''):
    global ok
    ok = ok and bool(condition)
    print('%s %s %s' % ('OK  ' if condition else 'FAIL', label, detail))


check('demo cargada', env['ir.config_parameter'].sudo().get_param('spa_demo.loaded_on'))  # noqa: F821
env.cr.execute("SELECT count(*) FROM account_move WHERE state = 'posted'")  # noqa: F821
posted = env.cr.fetchone()[0]  # noqa: F821
env.cr.execute("""
    SELECT m.name, SUM(l.debit) - SUM(l.credit) FROM account_move m JOIN account_move_line l ON l.move_id = m.id
     WHERE m.state = 'posted' GROUP BY m.id, m.name HAVING ABS(SUM(l.debit) - SUM(l.credit)) > 0.001""")  # noqa: F821
unbalanced = env.cr.fetchall()  # noqa: F821
check('asientos publicados cuadrados', not unbalanced and posted > 100,
      '(%s publicados, descuadrados: %s)' % (posted, unbalanced))
env.cr.execute("SELECT ROUND(SUM(debit) - SUM(credit), 2) FROM account_move_line WHERE parent_state = 'posted'")  # noqa
check('balance de comprobación suma cero', env.cr.fetchone()[0] == 0)  # noqa: F821

states = dict(env['spa.membership']._read_group([], ['state'], ['__count']))  # noqa: F821
for state in ('draft', 'active', 'grace', 'suspended', 'expired', 'cancelled'):
    check('membresías %-9s' % state, states.get(state, 0) >= 1, states.get(state, 0))
check('membresía congelada', env['spa.membership.freeze'].search_count([('state', '=', 'active')]))  # noqa: F821
check('bajada de plan programada',
      env['spa.membership'].search_count([('spa_next_plan_id', '!=', False)]))  # noqa: F821

dashboard = env['spa.report.dashboard'].create({})  # noqa: F821
for fname in ('people_inside', 'bookings_today', 'payments_pending', 'payments_pending_amount', 'members_active',
              'members_grace', 'members_suspended', 'members_new', 'members_overdue', 'amount_overdue', 'mrr',
              'revenue_month', 'leads_month', 'leads_won', 'conversion_rate'):
    value = dashboard[fname]
    optional = fname == 'people_inside'
    check('KPI %-24s' % fname, value > 0 or optional,
          '%s%s' % (value, ' (depende de la hora: sauna 10-20 h)' if optional else ''))

bookings = dict(env['spa.booking']._read_group([], ['state'], ['__count']))  # noqa: F821
check('reservas por estado', {'done', 'confirmed', 'late_cancel', 'no_show', 'cancelled'} <= set(bookings), bookings)
limited = env['spa.entitlement'].search([('unlimited', '=', False)])  # noqa: F821
check('saldos: usados <= otorgados + traslado', all(e.used <= e.granted + e.carried_in for e in limited), len(limited))
sessions = env['pos.session'].search([('state', '=', 'closed')])  # noqa: F821
check('POS: sesiones cerradas', len(sessions) >= 2, '%s sesiones, %s órdenes' % (len(sessions), len(sessions.order_ids)))
print('RESULT', 'OK' if ok else 'FAIL')
env.cr.rollback()  # noqa: F821
