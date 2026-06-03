packer {
  required_plugins {
    amazon = {
      version = ">= 1.3.0"
      source  = "github.com/hashicorp/amazon"
    }

    digitalocean = {
      version = ">= 1.4.0"
      source  = "github.com/digitalocean/digitalocean"
    }

    alicloud = {
      version = "~> 1.0"
      source  = "github.com/hashicorp/alicloud"
    }

    hcloud = {
      version = "~> 1.7"
      source  = "github.com/hetznercloud/hcloud"
    }
  }
}
