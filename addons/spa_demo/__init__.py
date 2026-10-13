# Part of ERP Servicios Spa. License LGPL-3.
import logging

from . import demo

_logger = logging.getLogger(__name__)


def _load_demo(env):
    demo.SpaDemoBuilder(env).load()


def post_init_hook(env):
    """Carga la demo cuando el plan contable ya está cargado.

    En una base nueva el plan contable boliviano se carga al final del arranque del registro
    (``registry._auto_install_template``, ver account, l10n_bo_spa y spa_pos): la demo se
    encadena después. En una base que ya tiene el plan, se carga de inmediato.
    """
    pending = getattr(env.registry, '_auto_install_template', None)
    if pending:
        def _load_chart_then_demo(env):
            pending(env)
            _load_demo(env)

        env.registry._auto_install_template = _load_chart_then_demo
    else:
        _load_demo(env)


def uninstall_hook(env):
    """La historia contable no se borra: solo se cierra el acceso de los usuarios de la demo."""
    logins = [login for _role, login, _name, _phone in demo.data.STAFF] + \
        [spec['portal'] for spec in demo.data.MEMBERS if spec.get('portal')]
    users = env['res.users'].with_context(active_test=False).search([('login', 'in', logins)])
    if users:
        users.write({'active': False})
        _logger.info('spa_demo: %s usuarios de la demo archivados.', len(users))
    env['ir.config_parameter'].sudo().search([('key', '=', demo.data.DEMO_PARAM)]).unlink()
