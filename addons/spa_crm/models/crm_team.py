# Part of ERP Servicios Spa. License LGPL-3.
from odoo import fields, models

SPA_PIPELINES = [
    ('acquisition', 'Captación'),
    ('retention', 'Retención'),
]

SPA_STAGE_CODES = [
    ('interested', 'Interesado'),
    ('visit', 'Visita de prueba / cortesía'),
    ('proposal', 'Propuesta'),
    ('member', 'Socio activo'),
    ('at_risk', 'En riesgo'),
    ('recovered', 'Recuperado'),
    ('ex_member', 'Ex-socio'),
]


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    spa_pipeline = fields.Selection(
        SPA_PIPELINES, string='Embudo del spa', index='btree_not_null',
        help='Indica qué embudo usa el spa para crear prospectos automáticamente '
             '(invitados, cortesías, socios en riesgo). Se busca primero el de la empresa '
             'y luego uno compartido.')


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    spa_stage_code = fields.Selection(
        SPA_STAGE_CODES, string='Función en el spa', index='btree_not_null',
        help='Permite al spa mover prospectos automáticamente aunque la etapa se renombre.')
