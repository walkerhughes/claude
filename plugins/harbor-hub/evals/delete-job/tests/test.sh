#!/bin/bash
# Verifier for the delete-job eval. Two rewards, both computed by rewardkit
# (baked into the image by environment/Dockerfile):
#
#   outcome  the job is really gone from the hub, and the agent said so
#   process  the delete went through the harbor-hub MCP server
#
# `outcome` alone cannot gate the MCP: the harbor CLI is on PATH for the oracle
# and the verifier, so an agent that ignores the MCP and shells out still deletes
# the job. `process` is what makes this an MCP eval.
rewardkit /tests
