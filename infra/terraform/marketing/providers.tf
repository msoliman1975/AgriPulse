provider "aws" {
  region = var.region

  default_tags {
    tags = local.common_tags
  }
}

# CloudFront requires ACM certs to be issued in us-east-1, regardless of where
# the origin or distribution edge cache lives. This alias is dedicated to that.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = local.common_tags
  }
}
