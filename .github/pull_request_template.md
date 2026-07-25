## Summary

Describe the change and the migration scenario it addresses.

## Validation

- [ ] Tests pass with `python -m unittest discover -s tests -v`
- [ ] `gitlab-migrator --help` still works
- [ ] Documentation is updated when behavior or commands change
- [ ] No tokens, keys, `.env` files, migration output, or customer data included
- [ ] Destructive operations remain dry runs unless explicitly requested
