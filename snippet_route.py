async def add_dynamic_routes():
    remote_spec = await brick.fetch_filtered_openapi()  # you already have this
    paths = remote_spec.get("paths", {})

    for path, methods in paths.items():
        get_op = methods.get("get")
        if not get_op:
            continue

        # Build a Param model (or None) from the operation's 'parameters'
        ParamModel = build_param_model_from_oas(get_op.get("parameters"), name=path.replace("/", "_") or "root")

        def make_dynamic_get(pth: str, ParamModel):
            if ParamModel:
                async def dynamic_get(params: ParamModel = Depends(), request: Request = None):  # type: ignore
                    q = {k: v for k, v in params.dict(exclude_none=True).items()}
                    headers = dict(request.headers) if request else {}
                    return await brick.proxy_get(pth.lstrip("/"), q, headers)
            else:
                async def dynamic_get(request: Request):
                    q = dict(request.query_params)
                    headers = dict(request.headers)
                    return await brick.proxy_get(pth.lstrip("/"), q, headers)
            return dynamic_get

        # mount under /landlord/<upstream>
        fastapi_path = "/landlord" + (path if path.startswith("/") else f"/{path}")
        router.add_api_route(
            fastapi_path,
            make_dynamic_get(path, ParamModel),
            methods=["GET"],
            include_in_schema=True,
            tags=get_op.get("tags") or ["landlord"],
            summary=get_op.get("summary"),
            description=get_op.get("description"),
        )