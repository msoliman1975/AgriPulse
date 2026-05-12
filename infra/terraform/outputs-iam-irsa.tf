output "iam_role_arns" {
  description = "IRSA role ARNs by service."
  value = {
    api              = module.iam_role_api.iam_role_arn
    workers          = module.iam_role_workers.iam_role_arn
    tile_server      = module.iam_role_tile_server.iam_role_arn
    external_secrets = module.iam_role_external_secrets.iam_role_arn
    cnpg             = module.iam_role_cnpg.iam_role_arn
  }
}
