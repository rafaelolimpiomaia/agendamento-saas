"""
Módulo de segurança: rate limiting, validação de preço, idempotência e webhook.
"""
import hashlib
import hmac
import logging
import time
from decimal import Decimal
from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger('pagamentos')


# ── RATE LIMITING ─────────────────────────────────────────────────────────────

def rate_limit(key_prefix, limit, period_seconds):
    """
    Decorator de rate limiting baseado em cache do Django.
    Funciona com qualquer backend de cache (memcache, redis, local).
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Identifica pelo IP real (considera proxy reverso)
            ip = (
                request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
                or request.META.get('REMOTE_ADDR', 'unknown')
            )
            cache_key = f'rl:{key_prefix}:{ip}'
            count = cache.get(cache_key, 0)

            if count >= limit:
                logger.warning(f'Rate limit atingido: {key_prefix} | IP={ip}')
                return JsonResponse(
                    {'erro': 'Muitas tentativas. Aguarde alguns instantes.'},
                    status=429
                )

            # Incrementa contador
            try:
                cache.add(cache_key, 0, period_seconds)
                cache.incr(cache_key)
            except Exception:
                pass  # falha silenciosa no rate limit nunca deve bloquear a view

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# ── VALIDAÇÃO DE PREÇO NO BACKEND ─────────────────────────────────────────────

def calcular_valor_pedido(pedido):
    """
    Recalcula o valor total do pedido a partir dos slots no banco.
    Nunca aceita o valor enviado pelo frontend como verdade.
    """
    total = Decimal('0')
    for slot in pedido.slots.select_related('servico').all():
        blocos_por_duracao = slot.servico.duracao_minutos / 30
        preco_por_bloco = Decimal(str(slot.servico.preco)) / Decimal(str(blocos_por_duracao))
        total += preco_por_bloco
    return total


def validar_valor_pagamento(pedido, valor_mp):
    """
    Valida se o valor aprovado pelo MP bate com o calculado no banco.
    Tolerância de R$ 0,01 por arredondamentos de float.
    """
    valor_esperado = calcular_valor_pedido(pedido)
    diferenca = abs(Decimal(str(valor_mp)) - valor_esperado)
    return diferenca <= Decimal('0.02')


# ── IDEMPOTÊNCIA DE PAGAMENTO ─────────────────────────────────────────────────

def pagamento_ja_processado(mp_payment_id):
    """
    Verifica se esse payment_id já foi processado com sucesso.
    Evita processamento duplicado em caso de webhook repetido.
    """
    cache_key = f'mp_processed:{mp_payment_id}'
    return cache.get(cache_key) is not None


def marcar_pagamento_processado(mp_payment_id, ttl=86400):
    """
    Marca o payment_id como processado. TTL padrão: 24h.
    """
    cache_key = f'mp_processed:{mp_payment_id}'
    cache.set(cache_key, True, ttl)


# ── VALIDAÇÃO DE WEBHOOK ──────────────────────────────────────────────────────

def validar_webhook_mercadopago(request):
    """
    Valida a autenticidade do webhook do Mercado Pago.
    Usa x-signature e x-request-id conforme documentação oficial.
    Retorna True se válido, False se inválido.
    """
    from django.conf import settings

    secret = getattr(settings, 'MP_WEBHOOK_SECRET', '')
    if not secret:
        # Se não há secret configurado, loga aviso mas não bloqueia em dev
        logger.warning('MP_WEBHOOK_SECRET não configurado — validação de webhook desativada')
        return True

    x_signature = request.META.get('HTTP_X_SIGNATURE', '')
    x_request_id = request.META.get('HTTP_X_REQUEST_ID', '')

    if not x_signature:
        logger.warning('Webhook recebido sem x-signature')
        return False

    # Extrai ts e hash do header x-signature
    # Formato: ts=<timestamp>,v1=<hash>
    parts = {}
    for part in x_signature.split(','):
        if '=' in part:
            k, v = part.split('=', 1)
            parts[k.strip()] = v.strip()

    ts = parts.get('ts', '')
    v1 = parts.get('v1', '')

    if not ts or not v1:
        logger.warning('Webhook com x-signature malformado')
        return False

    # Monta o manifest conforme documentação do MP
    data_id = request.GET.get('data.id', '')
    manifest = f'id:{data_id};request-id:{x_request_id};ts:{ts};'

    expected = hmac.new(
        secret.encode('utf-8'),
        manifest.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, v1):
        logger.warning(f'Webhook com assinatura inválida | data_id={data_id}')
        return False

    # Valida que o timestamp não é muito antigo (proteção replay attack — 5 min)
    try:
        age = int(time.time()) - int(ts)
        if age > 300:
            logger.warning(f'Webhook com timestamp muito antigo: {age}s')
            return False
    except (ValueError, TypeError):
        return False

    return True


# ── LOCKS DE CONCORRÊNCIA ─────────────────────────────────────────────────────

def adquirir_lock_slot(tenant_id, servico_id, data, horario, timeout=10):
    """
    Lock distribuído via cache para evitar dupla reserva simultânea.
    Retorna True se o lock foi adquirido, False se outro processo já tem.
    """
    cache_key = f'slot_lock:{tenant_id}:{servico_id}:{data}:{horario}'
    return cache.add(cache_key, True, timeout)


def liberar_lock_slot(tenant_id, servico_id, data, horario):
    cache_key = f'slot_lock:{tenant_id}:{servico_id}:{data}:{horario}'
    cache.delete(cache_key)