# CloudFront + AWS WAF (CLOUDFRONT scope, us-east-1) — deployment-and-operations §4.4, §4.5.
# Skeleton: managed rule groups and the main rate-based rules in the documented priority order.
# TODO: custom body-size rules for /api/v1/coding/* and /api/v1/attempts/*, IP sets
# td-trusted-campus / td-abuse-challenge, bot-control scope-down, staging IP allowlist,
# WAF logging with redacted fields, S3 OAC origins and signed-URL key group.

resource "aws_wafv2_web_acl" "this" {
  provider = aws.us_east_1

  name        = "td-${var.env}"
  description = "Tech Drona ${var.env} edge ACL"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # 2-7: AWS managed rule groups (AnonymousIpList is count-only: never block on IP alone)
  dynamic "rule" {
    for_each = {
      AWSManagedRulesAmazonIpReputationList = { priority = 20, count_only = false }
      AWSManagedRulesCommonRuleSet          = { priority = 30, count_only = false }
      AWSManagedRulesKnownBadInputsRuleSet  = { priority = 40, count_only = false }
      AWSManagedRulesSQLiRuleSet            = { priority = 50, count_only = false }
      AWSManagedRulesAnonymousIpList        = { priority = 60, count_only = true }
    }
    content {
      name     = rule.key
      priority = rule.value.priority

      override_action {
        dynamic "none" {
          for_each = rule.value.count_only ? [] : [1]
          content {}
        }
        dynamic "count" {
          for_each = rule.value.count_only ? [1] : []
          content {}
        }
      }

      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = rule.key
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.key
        sampled_requests_enabled   = true
      }
    }
  }

  # 8: auth endpoints rate limit -> CAPTCHA challenge
  rule {
    name     = "rate-auth"
    priority = 80

    action {
      captcha {}
    }

    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"

        scope_down_statement {
          byte_match_statement {
            search_string         = "/api/v1/auth/"
            positional_constraint = "STARTS_WITH"

            field_to_match {
              uri_path {}
            }

            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-auth"
      sampled_requests_enabled   = true
    }
  }

  # 9: global per-IP rate limit
  rule {
    name     = "rate-global"
    priority = 90

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 6000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-global"
      sampled_requests_enabled   = true
    }
  }

  # 11: block API docs / metrics at the edge in prod
  dynamic "rule" {
    for_each = var.block_docs ? [1] : []
    content {
      name     = "block-docs"
      priority = 110

      action {
        block {}
      }

      statement {
        regex_match_statement {
          regex_string = "^/(docs|openapi\\.json|redoc|metrics|healthz/deep)"

          field_to_match {
            uri_path {}
          }

          text_transformation {
            priority = 0
            type     = "NONE"
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "block-docs"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "td-${var.env}"
    sampled_requests_enabled   = true
  }
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = "td-${var.env}-security-headers"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 63072000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }

    content_type_options {
      override = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = "PriceClass_200"
  aliases         = var.aliases
  web_acl_id      = aws_wafv2_web_acl.this.arn
  comment         = "td-${var.env}"

  origin {
    origin_id   = "alb"
    domain_name = var.alb_dns_name

    custom_header {
      name  = "X-TD-Origin-Verify"
      value = var.origin_verify_header_value
    }

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Webhooks: ordered before /api/*, never cached, no cookies
  ordered_cache_behavior {
    path_pattern             = "/api/v1/webhooks/*"
    target_origin_id         = "alb"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
  }

  ordered_cache_behavior {
    path_pattern               = "/_next/static/*"
    target_origin_id           = "alb"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  default_cache_behavior {
    target_origin_id           = "alb"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.cloudfront_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  dynamic "logging_config" {
    for_each = var.log_bucket_domain_name == null ? [] : [1]
    content {
      bucket = var.log_bucket_domain_name
      prefix = "cloudfront/td-${var.env}/"
    }
  }
}
