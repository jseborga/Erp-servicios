# ERP Servicios Spa — imagen Odoo 19 Community con el plan de cuentas del spa
# y módulos OCA de reportes contables y activos fijos.
#
# Base: imagen oficial de Odoo (Docker Hub "odoo"). Se fija la rama 19.0:
# la etiqueta "latest" ya apunta a Odoo 20 y NO debe usarse.
# Para fijar una compilación exacta: --build-arg ODOO_IMAGE=odoo:19.0-20260926
ARG ODOO_IMAGE=odoo:19.0
FROM ${ODOO_IMAGE}

USER root

# Módulos OCA fijados por commit (ver third_party/oca/README.md) y módulos propios.
COPY third_party/oca /opt/odoo/oca-addons
COPY addons /opt/odoo/custom-addons
COPY docker/entrypoint-spa.sh /usr/local/bin/entrypoint-spa.sh

RUN chmod 755 /usr/local/bin/entrypoint-spa.sh \
    && chown -R odoo /etc/odoo \
    && chmod -R a+rX /opt/odoo

USER odoo

ENTRYPOINT ["/usr/local/bin/entrypoint-spa.sh"]
CMD ["odoo"]
