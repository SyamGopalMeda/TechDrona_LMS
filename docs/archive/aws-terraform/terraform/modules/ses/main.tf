# SES in ap-south-1 (deployment-and-operations §5): domain identity with Easy DKIM, custom
# MAIL FROM, configuration sets td-transactional / td-marketing, bounce/complaint -> SNS ->
# worker-notifications suppression. DNS records are created in the env (Route 53, TBD domain).

resource "aws_sesv2_email_identity" "domain" {
  email_identity = var.domain

  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }
}

resource "aws_sesv2_email_identity_mail_from_attributes" "domain" {
  email_identity         = aws_sesv2_email_identity.domain.email_identity
  mail_from_domain       = "mail.${var.domain}"
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}

resource "aws_sns_topic" "feedback" {
  name              = "td-${var.env}-ses-feedback"
  kms_master_key_id = var.sns_kms_key_arn
}

resource "aws_sesv2_configuration_set" "this" {
  for_each = toset(["td-transactional", "td-marketing"])

  configuration_set_name = "${each.value}-${var.env}"

  reputation_options {
    reputation_metrics_enabled = true
  }

  suppression_options {
    suppressed_reasons = ["BOUNCE", "COMPLAINT"]
  }
}

resource "aws_sesv2_configuration_set_event_destination" "feedback" {
  for_each = aws_sesv2_configuration_set.this

  configuration_set_name = each.value.configuration_set_name
  event_destination_name = "sns-feedback"

  event_destination {
    enabled              = true
    matching_event_types = ["BOUNCE", "COMPLAINT", "REJECT"]

    sns_destination {
      topic_arn = aws_sns_topic.feedback.arn
    }
  }
}
