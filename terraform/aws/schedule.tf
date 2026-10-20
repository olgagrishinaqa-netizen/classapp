# Расписание работы ВМ: днём работает, ночью остановлена (платим только за диск и IP).
# EventBridge Scheduler сам вызывает ec2:StartInstances / ec2:StopInstances, часовой пояс
# задаётся явно (Минск — UTC+3 без перехода на летнее время). Elastic IP остаётся прежним.

locals {
  scheduler_target_prefix = "arn:aws:scheduler:::aws-sdk:ec2"
}

resource "aws_iam_role" "scheduler" {
  count = var.schedule_enabled ? 1 : 0
  name  = "${var.name_prefix}-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  count = var.schedule_enabled ? 1 : 0
  name  = "${var.name_prefix}-start-stop"
  role  = aws_iam_role.scheduler[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ec2:StartInstances", "ec2:StopInstances"]
      Resource = "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.k3s.id}"
    }]
  })
}

resource "aws_scheduler_schedule" "start" {
  count                        = var.schedule_enabled ? 1 : 0
  name                         = "${var.name_prefix}-vm-start"
  description                  = "Запуск ВМ classapp утром"
  schedule_expression          = "cron(${var.schedule_start_minute} ${var.schedule_start_hour} * * ? *)"
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "${local.scheduler_target_prefix}:startInstances"
    role_arn = aws_iam_role.scheduler[0].arn
    input    = jsonencode({ InstanceIds = [aws_instance.k3s.id] })
  }
}

resource "aws_scheduler_schedule" "stop" {
  count                        = var.schedule_enabled ? 1 : 0
  name                         = "${var.name_prefix}-vm-stop"
  description                  = "Остановка ВМ classapp на ночь"
  schedule_expression          = "cron(${var.schedule_stop_minute} ${var.schedule_stop_hour} * * ? *)"
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "${local.scheduler_target_prefix}:stopInstances"
    role_arn = aws_iam_role.scheduler[0].arn
    input    = jsonencode({ InstanceIds = [aws_instance.k3s.id] })
  }
}
