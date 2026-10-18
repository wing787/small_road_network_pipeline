terraform {
  # Terraform 本体の版。今入っているのは 1.16.6
  required_version = "~>1.16"

  required_providers {
    aws = {
      # Terraform Registry 上の住所。registry.terraform.io/hashicorp/aws の省略形
      source = "hashicorp/aws"
      # 6 系の中でだけ上げる。実際の版は .terraform.lock.hcl が固定する
      version = "~> 6.0"
    }
  }
}
