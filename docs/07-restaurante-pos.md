# 07 · Restaurante y cafetería (POS)

Base: `point_of_sale` + `pos_restaurant` (Odoo CE 19), extendido por `spa_pos`.

## Configuración
- **Dos puntos de venta**: Restaurante (con plano de mesas) y Cafetería/Mostrador. Ambos con **comanda abierta** que se cierra al pagar.
- Envío de comandas a cocina y barra. **Ojo:** el módulo de pantalla de preparación (`pos_preparation_display`) **no está en CE 19**; la vía estándar es impresión de comandas en impresoras de cocina. Alternativas en `docs/13`.

## Extensiones `spa_pos`
1. **Identificar al socio** en la comanda (búsqueda por nombre, CI o QR de la credencial).
2. **Descuento por plan**: al asignar el socio, se aplica el % configurado por categoría (p. ej. Premium 10 % cafetería). Implementación preferente: listas de precios por plan (`product.pricelist`) asignadas automáticamente al socio.
3. **Cargo a cuenta del socio**: método de pago "Cuenta del socio" → cuenta por cobrar del partner; se liquida en el siguiente pago o al cierre de mes. Límite de crédito configurable por plan.
4. **Consumo dentro de la membresía** (opcional): si un plan incluye, p. ej., "1 café diario", se registra como consumo de un derecho (`spa.consumption`) con precio 0.

## Facturación desde el POS
Cada orden: factura electrónica SIAT vía `l10n_bo_siat_edi` o venta sin factura según configuración (ver advertencias en `docs/05`).

## Inventario y costeo
- **Fase 1**: compras y ventas con inventario básico (`stock`), sin recetas.
- **Fase posterior**: listas de materiales (`mrp`, disponible en CE 19) por plato para costeo y descuento de insumos. La estructura de productos se define desde el inicio para no migrar después (productos de venta separados de insumos).

## Analítica
Toda venta del POS lleva la analítica "Restaurante" o "Cafetería" para la rentabilidad por área.
