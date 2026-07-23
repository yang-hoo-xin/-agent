using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

if (args.Length < 2)
{
    Console.Error.WriteLine("usage: r8_il_inspector <assembly> <Type.Method> [<Type.Method> ...]");
    Console.Error.WriteLine("   or: r8_il_inspector <assembly> --find-metadata <literal-substring> [<literal-substring> ...]");
    Console.Error.WriteLine("   or: r8_il_inspector <consumer-assembly> --resolve-direct-boolean-member-accesses <dependency-root> <consumer-declaring-type> <receiver-member>");
    return 2;
}

var assemblyPath = Path.GetFullPath(args[0]);
await using var stream = File.OpenRead(assemblyPath);
using var peReader = new PEReader(stream, PEStreamOptions.LeaveOpen);
if (!peReader.HasMetadata)
{
    Console.Error.WriteLine("assembly has no CLI metadata");
    return 3;
}

var metadata = peReader.GetMetadataReader();
var module = metadata.GetModuleDefinition();
var assemblySha256 = Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(assemblyPath)));
if (args[1] == "--resolve-direct-boolean-member-accesses")
{
    try
    {
        return ResolveDirectBooleanMemberAccesses(
            assemblyPath,
            metadata,
            assemblySha256,
            args.Skip(2).ToArray());
    }
    catch (Exception exception) when (
        exception is ArgumentException
        or BadImageFormatException
        or InvalidOperationException
        or IOException
        or UnauthorizedAccessException)
    {
        Console.Error.WriteLine(exception.Message);
        return 5;
    }
}
if (args[1] == "--find-metadata")
{
    if (args.Length < 3)
    {
        Console.Error.WriteLine("--find-metadata requires at least one literal substring");
        return 2;
    }

    var queries = args.Skip(2).ToArray();
    var types = new List<object>();
    var methodsFound = new List<object>();
    var fields = new List<object>();
    foreach (var typeHandle in metadata.TypeDefinitions)
    {
        var type = metadata.GetTypeDefinition(typeHandle);
        var typeName = FullTypeName(metadata, typeHandle);
        if (queries.Any(query => typeName.Contains(query, StringComparison.OrdinalIgnoreCase)))
        {
            types.Add(new
            {
                symbol = typeName,
                metadata_token = $"0x{MetadataTokens.GetToken(typeHandle):X8}",
                attributes = type.Attributes.ToString(),
            });
        }
        foreach (var methodHandle in type.GetMethods())
        {
            var method = metadata.GetMethodDefinition(methodHandle);
            var symbol = $"{typeName}.{metadata.GetString(method.Name)}";
            if (queries.Any(query => symbol.Contains(query, StringComparison.OrdinalIgnoreCase)))
            {
                methodsFound.Add(new
                {
                    symbol,
                    metadata_token = $"0x{MetadataTokens.GetToken(methodHandle):X8}",
                    attributes = method.Attributes.ToString(),
                    impl_attributes = method.ImplAttributes.ToString(),
                    signature_blob = Convert.ToHexString(metadata.GetBlobBytes(method.Signature)),
                    rva = method.RelativeVirtualAddress,
                    has_method_body = method.RelativeVirtualAddress != 0,
                });
            }
        }
        foreach (var fieldHandle in type.GetFields())
        {
            var field = metadata.GetFieldDefinition(fieldHandle);
            var symbol = $"{typeName}.{metadata.GetString(field.Name)}";
            if (queries.Any(query => symbol.Contains(query, StringComparison.OrdinalIgnoreCase)))
            {
                fields.Add(new
                {
                    symbol,
                    metadata_token = $"0x{MetadataTokens.GetToken(fieldHandle):X8}",
                    attributes = field.Attributes.ToString(),
                    signature_blob = Convert.ToHexString(metadata.GetBlobBytes(field.Signature)),
                });
            }
        }
    }
    var searchOutput = new
    {
        schema_version = "cli_metadata_search_v1",
        assembly_path = assemblyPath,
        assembly_sha256 = assemblySha256,
        module_name = metadata.GetString(module.Name),
        module_mvid = metadata.GetGuid(module.Mvid).ToString("D"),
        queries,
        types,
        methods = methodsFound,
        fields,
        target_code_executed = false,
    };
    Console.WriteLine(JsonSerializer.Serialize(searchOutput, new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

var requestedSymbols = args.Skip(1).ToHashSet(StringComparer.Ordinal);
var opcodeMap = BuildOpcodeMap();
var methods = new List<object>();
foreach (var typeHandle in metadata.TypeDefinitions)
{
    var type = metadata.GetTypeDefinition(typeHandle);
    var typeName = FullTypeName(metadata, typeHandle);
    foreach (var methodHandle in type.GetMethods())
    {
        var method = metadata.GetMethodDefinition(methodHandle);
        var methodName = metadata.GetString(method.Name);
        var symbol = $"{typeName}.{methodName}";
        if (!requestedSymbols.Contains(symbol))
        {
            continue;
        }

        var signature = Convert.ToHexString(metadata.GetBlobBytes(method.Signature));
        var token = MetadataTokens.GetToken(methodHandle);
        if (method.RelativeVirtualAddress == 0)
        {
            methods.Add(new
            {
                symbol,
                metadata_token = $"0x{token:X8}",
                attributes = method.Attributes.ToString(),
                impl_attributes = method.ImplAttributes.ToString(),
                signature_blob = signature,
                custom_attributes = CustomAttributes(metadata, method.GetCustomAttributes()),
                declaring_type_custom_attributes = CustomAttributes(metadata, type.GetCustomAttributes()),
                rva = 0,
                has_method_body = false,
                il_bytes = "",
                instructions = Array.Empty<object>(),
            });
            continue;
        }

        var body = peReader.GetMethodBody(method.RelativeVirtualAddress);
        var il = body.GetILBytes() ?? Array.Empty<byte>();
        methods.Add(new
        {
            symbol,
            metadata_token = $"0x{token:X8}",
            attributes = method.Attributes.ToString(),
            impl_attributes = method.ImplAttributes.ToString(),
            signature_blob = signature,
            custom_attributes = CustomAttributes(metadata, method.GetCustomAttributes()),
            declaring_type_custom_attributes = CustomAttributes(metadata, type.GetCustomAttributes()),
            rva = method.RelativeVirtualAddress,
            has_method_body = true,
            max_stack = body.MaxStack,
            local_signature_token = body.LocalSignature.IsNil
                ? null
                : $"0x{MetadataTokens.GetToken(body.LocalSignature):X8}",
            exception_region_count = body.ExceptionRegions.Length,
            il_bytes = Convert.ToHexString(il),
            instructions = DecodeInstructions(il, metadata, opcodeMap),
        });
    }
}

var foundSymbols = methods
    .Select(item => (string)item.GetType().GetProperty("symbol")!.GetValue(item)!)
    .ToHashSet(StringComparer.Ordinal);
var missingSymbols = requestedSymbols.Except(foundSymbols).OrderBy(value => value).ToArray();
var output = new
{
    schema_version = "r8_il_inspection_v1",
    assembly_path = assemblyPath,
    assembly_sha256 = assemblySha256,
    module_name = metadata.GetString(module.Name),
    module_mvid = metadata.GetGuid(module.Mvid).ToString("D"),
    methods,
    missing_symbols = missingSymbols,
    target_code_executed = false,
};
Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }));
return missingSymbols.Length == 0 ? 0 : 4;

static int ResolveDirectBooleanMemberAccesses(
    string consumerAssemblyPath,
    MetadataReader consumerMetadata,
    string consumerAssemblySha256,
    string[] arguments)
{
    if (arguments.Length != 3)
    {
        throw new ArgumentException(
            "--resolve-direct-boolean-member-accesses requires dependency root, "
            + "consumer declaring type, and receiver member");
    }

    var dependencyRoot = Path.GetFullPath(arguments[0]);
    var consumerDeclaringType = arguments[1];
    var receiverMember = arguments[2];
    if (!Directory.Exists(dependencyRoot))
    {
        throw new InvalidOperationException("dependency root is missing");
    }

    var consumerTypeHandles = consumerMetadata.TypeDefinitions
        .Where(handle => FullTypeName(consumerMetadata, handle) == consumerDeclaringType)
        .ToArray();
    if (consumerTypeHandles.Length != 1)
    {
        throw new InvalidOperationException(
            "consumer declaring type did not resolve to one exact metadata type");
    }

    var provider = new ExactTypeShapeProvider();
    var consumerType = consumerMetadata.GetTypeDefinition(consumerTypeHandles[0]);
    var consumerMembers = new List<ConsumerMemberValue>();
    foreach (var propertyHandle in consumerType.GetProperties())
    {
        var property = consumerMetadata.GetPropertyDefinition(propertyHandle);
        if (consumerMetadata.GetString(property.Name) != receiverMember)
        {
            continue;
        }
        var accessors = property.GetAccessors();
        if (accessors.Getter.IsNil)
        {
            continue;
        }
        var getter = consumerMetadata.GetMethodDefinition(accessors.Getter);
        var signature = property.DecodeSignature(provider, GenericContextValue.Empty);
        consumerMembers.Add(new ConsumerMemberValue(
            "property",
            (getter.Attributes & MethodAttributes.Static) != 0,
            MetadataTokens.GetToken(propertyHandle),
            Convert.ToHexString(consumerMetadata.GetBlobBytes(property.Signature)),
            signature.ReturnType));
    }
    foreach (var fieldHandle in consumerType.GetFields())
    {
        var field = consumerMetadata.GetFieldDefinition(fieldHandle);
        if (consumerMetadata.GetString(field.Name) != receiverMember)
        {
            continue;
        }
        consumerMembers.Add(new ConsumerMemberValue(
            "field",
            (field.Attributes & FieldAttributes.Static) != 0,
            MetadataTokens.GetToken(fieldHandle),
            Convert.ToHexString(consumerMetadata.GetBlobBytes(field.Signature)),
            field.DecodeSignature(provider, GenericContextValue.Empty)));
    }
    if (consumerMembers.Count != 1)
    {
        throw new InvalidOperationException(
            "receiver member did not resolve to one exact compiled property or field");
    }

    var consumerMember = consumerMembers[0];
    var receiverType = consumerMember.ReceiverType;
    if (receiverType.Kind != "generic_instance"
        || receiverType.DefinitionHandle.Kind != HandleKind.TypeReference
        || receiverType.TypeArguments.IsDefaultOrEmpty)
    {
        throw new InvalidOperationException(
            "receiver member type is not a directly constructed external generic type");
    }

    var receiverTypeReferenceHandle = (TypeReferenceHandle)receiverType.DefinitionHandle;
    var receiverTypeReference = consumerMetadata.GetTypeReference(
        receiverTypeReferenceHandle);
    if (receiverTypeReference.ResolutionScope.Kind != HandleKind.AssemblyReference)
    {
        throw new InvalidOperationException(
            "receiver TypeRef resolution scope is not one direct AssemblyRef");
    }
    var assemblyReferenceHandle = (AssemblyReferenceHandle)receiverTypeReference.ResolutionScope;
    var assemblyReference = AssemblyReferenceIdentity(
        consumerMetadata,
        assemblyReferenceHandle);
    var resolvedAssembly = ResolvePhysicalAssembly(
        dependencyRoot,
        assemblyReference);

    var verifiedMemberAccesses = ReadDirectBooleanPropertyAccesses(
        resolvedAssembly.Path,
        receiverType.DefinitionName,
        receiverType.TypeArguments);
    if (verifiedMemberAccesses.Count == 0)
    {
        throw new InvalidOperationException(
            "receiver type exposes no public non-static readable non-index property "
            + "whose direct generic return closes to System.Boolean");
    }
    if (Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(consumerAssemblyPath)))
        != consumerAssemblySha256)
    {
        throw new InvalidOperationException(
            "consumer assembly changed during member resolution");
    }
    if (Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(resolvedAssembly.Path)))
        != resolvedAssembly.Sha256)
    {
        throw new InvalidOperationException(
            "resolved assembly changed during member resolution");
    }

    var consumerModule = consumerMetadata.GetModuleDefinition();
    var output = new
    {
        schema_version = "dotnet_direct_boolean_member_access_resolution_v1",
        request = new
        {
            consumer_declaring_type = consumerDeclaringType,
            receiver_member = receiverMember,
        },
        consumer = new
        {
            assembly_sha256 = consumerAssemblySha256,
            module_name = consumerMetadata.GetString(consumerModule.Name),
            module_mvid = consumerMetadata.GetGuid(consumerModule.Mvid).ToString("D"),
            declaring_type = consumerDeclaringType,
            receiver_member = receiverMember,
            member_kind = consumerMember.MemberKind,
            is_static = consumerMember.IsStatic,
            member_metadata_token = $"0x{consumerMember.MetadataToken:X8}",
            signature_blob = consumerMember.SignatureBlob,
            receiver_closed_type = receiverType.DisplayName,
        },
        type_reference = new
        {
            symbol = receiverType.DefinitionName,
            metadata_token = $"0x{MetadataTokens.GetToken(receiverTypeReferenceHandle):X8}",
            resolution_scope_kind = receiverTypeReference.ResolutionScope.Kind.ToString(),
            resolution_scope_metadata_token =
                $"0x{MetadataTokens.GetToken(receiverTypeReference.ResolutionScope):X8}",
        },
        assembly_reference = new
        {
            metadata_token = $"0x{MetadataTokens.GetToken(assemblyReferenceHandle):X8}",
            name = assemblyReference.Identity.Name,
            version = assemblyReference.Identity.Version,
            culture = assemblyReference.Identity.Culture,
            public_key_token = assemblyReference.Identity.PublicKeyToken,
            flags = assemblyReference.Flags,
            hash_value = assemblyReference.HashValue,
        },
        resolved_assembly = new
        {
            relative_path = resolvedAssembly.RelativePath,
            assembly_sha256 = resolvedAssembly.Sha256,
            module_name = resolvedAssembly.ModuleName,
            module_mvid = resolvedAssembly.ModuleMvid,
            assembly_definition = new
            {
                name = resolvedAssembly.Identity.Name,
                version = resolvedAssembly.Identity.Version,
                culture = resolvedAssembly.Identity.Culture,
                public_key_token = resolvedAssembly.Identity.PublicKeyToken,
                flags = resolvedAssembly.Flags,
            },
        },
        verified_member_accesses = verifiedMemberAccesses,
        target_code_executed = false,
    };
    Console.WriteLine(JsonSerializer.Serialize(
        output,
        new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

static AssemblyReferenceValue AssemblyReferenceIdentity(
    MetadataReader metadata,
    AssemblyReferenceHandle handle)
{
    var reference = metadata.GetAssemblyReference(handle);
    var keyOrToken = metadata.GetBlobBytes(reference.PublicKeyOrToken);
    var token = (reference.Flags & AssemblyFlags.PublicKey) != 0
        ? ComputePublicKeyToken(keyOrToken)
        : keyOrToken;
    return new AssemblyReferenceValue(
        new AssemblyIdentityValue(
            metadata.GetString(reference.Name),
            reference.Version.ToString(),
            reference.Culture.IsNil ? "" : metadata.GetString(reference.Culture),
            Convert.ToHexString(token)),
        reference.Flags.ToString(),
        Convert.ToHexString(metadata.GetBlobBytes(reference.HashValue)));
}

static ResolvedAssemblyValue ResolvePhysicalAssembly(
    string dependencyRoot,
    AssemblyReferenceValue reference)
{
    var matches = new List<ResolvedAssemblyValue>();
    foreach (var path in Directory.EnumerateFiles(
        dependencyRoot,
        "*.dll",
        SearchOption.AllDirectories))
    {
        try
        {
            using var stream = File.OpenRead(path);
            using var peReader = new PEReader(stream);
            if (!peReader.HasMetadata)
            {
                continue;
            }
            var metadata = peReader.GetMetadataReader();
            if (!metadata.IsAssembly)
            {
                continue;
            }
            var definition = metadata.GetAssemblyDefinition();
            var identity = new AssemblyIdentityValue(
                metadata.GetString(definition.Name),
                definition.Version.ToString(),
                definition.Culture.IsNil ? "" : metadata.GetString(definition.Culture),
                Convert.ToHexString(ComputePublicKeyToken(
                    metadata.GetBlobBytes(definition.PublicKey))));
            if (identity != reference.Identity)
            {
                continue;
            }
            var module = metadata.GetModuleDefinition();
            matches.Add(new ResolvedAssemblyValue(
                Path.GetFullPath(path),
                Path.GetRelativePath(dependencyRoot, path).Replace('\\', '/'),
                Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))),
                metadata.GetString(module.Name),
                metadata.GetGuid(module.Mvid).ToString("D"),
                identity,
                definition.Flags.ToString()));
        }
        catch (BadImageFormatException)
        {
            continue;
        }
    }
    if (matches.Count != 1)
    {
        throw new InvalidOperationException(
            "AssemblyRef identity did not resolve to one run-local physical assembly");
    }
    return matches[0];
}

static List<object> ReadDirectBooleanPropertyAccesses(
    string assemblyPath,
    string declaringTypeName,
    ImmutableArray<TypeShape> closedTypeArguments)
{
    using var stream = File.OpenRead(assemblyPath);
    using var peReader = new PEReader(stream);
    var metadata = peReader.GetMetadataReader();
    var typeHandles = metadata.TypeDefinitions
        .Where(handle => FullTypeName(metadata, handle) == declaringTypeName)
        .ToArray();
    if (typeHandles.Length != 1)
    {
        throw new InvalidOperationException(
            "declaration assembly does not contain one exact receiver type definition");
    }
    var typeHandle = typeHandles[0];
    var type = metadata.GetTypeDefinition(typeHandle);
    if (type.GetGenericParameters().Count != closedTypeArguments.Length)
    {
        throw new InvalidOperationException(
            "receiver generic arity does not match the declaration type");
    }

    var provider = new ExactTypeShapeProvider();
    var context = new GenericContextValue(closedTypeArguments);
    var result = new List<object>();
    foreach (var propertyHandle in type.GetProperties())
    {
        var property = metadata.GetPropertyDefinition(propertyHandle);
        var accessors = property.GetAccessors();
        if (accessors.Getter.IsNil)
        {
            continue;
        }
        var getter = metadata.GetMethodDefinition(accessors.Getter);
        if ((getter.Attributes & MethodAttributes.MemberAccessMask) != MethodAttributes.Public
            || (getter.Attributes & MethodAttributes.Static) != 0)
        {
            continue;
        }
        var signature = property.DecodeSignature(provider, context);
        if (signature.ParameterTypes.Length != 0
            || signature.ReturnType.DisplayName != "System.Boolean"
            || signature.ReturnType.ClosedFromTypeParameterIndex is null)
        {
            continue;
        }
        result.Add(new
        {
            declaring_type = declaringTypeName,
            declaring_type_metadata_token =
                $"0x{MetadataTokens.GetToken(typeHandle):X8}",
            member_name = metadata.GetString(property.Name),
            member_kind = "property",
            access_kind = "instance_property_get",
            property_metadata_token =
                $"0x{MetadataTokens.GetToken(propertyHandle):X8}",
            getter_metadata_token =
                $"0x{MetadataTokens.GetToken(accessors.Getter):X8}",
            property_signature_blob =
                Convert.ToHexString(metadata.GetBlobBytes(property.Signature)),
            generic_result_type_parameter_index =
                signature.ReturnType.ClosedFromTypeParameterIndex,
            closed_result_type = signature.ReturnType.DisplayName,
        });
    }
    return result;
}

static byte[] ComputePublicKeyToken(byte[] publicKey)
{
    if (publicKey.Length == 0)
    {
        return Array.Empty<byte>();
    }
    var hash = SHA1.HashData(publicKey);
    return hash[^8..].Reverse().ToArray();
}

static Dictionary<ushort, OpCode> BuildOpcodeMap()
{
    var result = new Dictionary<ushort, OpCode>();
    foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
    {
        if (field.GetValue(null) is OpCode opcode)
        {
            result[unchecked((ushort)opcode.Value)] = opcode;
        }
    }
    return result;
}

static List<object> DecodeInstructions(
    byte[] il,
    MetadataReader metadata,
    Dictionary<ushort, OpCode> opcodeMap)
{
    var instructions = new List<object>();
    var offset = 0;
    while (offset < il.Length)
    {
        var instructionOffset = offset;
        ushort opcodeValue = il[offset++];
        if (opcodeValue == 0xFE)
        {
            if (offset >= il.Length)
            {
                throw new BadImageFormatException("truncated two-byte IL opcode");
            }
            opcodeValue = (ushort)(0xFE00 | il[offset++]);
        }
        if (!opcodeMap.TryGetValue(opcodeValue, out var opcode))
        {
            throw new BadImageFormatException($"unknown IL opcode 0x{opcodeValue:X4}");
        }

        object? operand = null;
        string? resolved = null;
        switch (opcode.OperandType)
        {
            case OperandType.InlineNone:
                break;
            case OperandType.ShortInlineI:
                operand = opcode == OpCodes.Ldc_I4_S ? (sbyte)il[offset] : il[offset];
                offset += 1;
                break;
            case OperandType.InlineI:
                operand = ReadInt32(il, ref offset);
                break;
            case OperandType.InlineI8:
                operand = ReadInt64(il, ref offset);
                break;
            case OperandType.ShortInlineR:
                operand = BitConverter.Int32BitsToSingle(ReadInt32(il, ref offset));
                break;
            case OperandType.InlineR:
                operand = BitConverter.Int64BitsToDouble(ReadInt64(il, ref offset));
                break;
            case OperandType.ShortInlineBrTarget:
            {
                var delta = (sbyte)il[offset++];
                operand = $"IL_{offset + delta:X4}";
                break;
            }
            case OperandType.InlineBrTarget:
            {
                var delta = ReadInt32(il, ref offset);
                operand = $"IL_{offset + delta:X4}";
                break;
            }
            case OperandType.InlineSwitch:
            {
                var count = ReadInt32(il, ref offset);
                var baseOffset = offset + (count * 4);
                var targets = new string[count];
                for (var index = 0; index < count; index++)
                {
                    targets[index] = $"IL_{baseOffset + ReadInt32(il, ref offset):X4}";
                }
                operand = targets;
                break;
            }
            case OperandType.InlineVar:
                operand = ReadUInt16(il, ref offset);
                break;
            case OperandType.ShortInlineVar:
                operand = il[offset++];
                break;
            case OperandType.InlineString:
            {
                var token = ReadInt32(il, ref offset);
                operand = $"0x{token:X8}";
                resolved = metadata.GetUserString(MetadataTokens.UserStringHandle(token & 0x00FFFFFF));
                break;
            }
            case OperandType.InlineField:
            case OperandType.InlineMethod:
            case OperandType.InlineType:
            case OperandType.InlineTok:
            case OperandType.InlineSig:
            {
                var token = ReadInt32(il, ref offset);
                operand = $"0x{token:X8}";
                resolved = ResolveToken(metadata, token);
                break;
            }
            default:
                throw new NotSupportedException($"unsupported operand type {opcode.OperandType}");
        }
        instructions.Add(new
        {
            offset = $"IL_{instructionOffset:X4}",
            opcode = opcode.Name,
            operand,
            resolved,
        });
    }
    return instructions;
}

static string ResolveToken(MetadataReader metadata, int token)
{
    try
    {
        var handle = MetadataTokens.EntityHandle(token);
        return handle.Kind switch
        {
            HandleKind.MethodDefinition => MethodName(metadata, (MethodDefinitionHandle)handle),
            HandleKind.MemberReference => MemberReferenceName(metadata, (MemberReferenceHandle)handle),
            HandleKind.MethodSpecification => ResolveToken(
                metadata,
                MetadataTokens.GetToken(metadata.GetMethodSpecification((MethodSpecificationHandle)handle).Method)),
            HandleKind.FieldDefinition => FieldName(metadata, (FieldDefinitionHandle)handle),
            HandleKind.TypeDefinition => FullTypeName(metadata, (TypeDefinitionHandle)handle),
            HandleKind.TypeReference => ReferencedTypeName(metadata, (TypeReferenceHandle)handle),
            HandleKind.TypeSpecification => $"TypeSpec:{Convert.ToHexString(metadata.GetBlobBytes(metadata.GetTypeSpecification((TypeSpecificationHandle)handle).Signature))}",
            HandleKind.StandaloneSignature => $"Signature:{Convert.ToHexString(metadata.GetBlobBytes(metadata.GetStandaloneSignature((StandaloneSignatureHandle)handle).Signature))}",
            _ => handle.Kind.ToString(),
        };
    }
    catch (Exception exception) when (exception is ArgumentException or BadImageFormatException)
    {
        return $"unresolved:{exception.Message}";
    }
}

static List<object> CustomAttributes(MetadataReader metadata, CustomAttributeHandleCollection handles)
{
    var attributes = new List<object>();
    foreach (var handle in handles)
    {
        var attribute = metadata.GetCustomAttribute(handle);
        var value = metadata.GetBlobBytes(attribute.Value);
        attributes.Add(new
        {
            constructor = ResolveToken(metadata, MetadataTokens.GetToken(attribute.Constructor)),
            value_blob = Convert.ToHexString(value),
            printable_ascii_runs = PrintableAsciiRuns(value),
        });
    }
    return attributes;
}

static string[] PrintableAsciiRuns(byte[] bytes)
{
    var runs = new List<string>();
    var current = new List<byte>();
    foreach (var value in bytes)
    {
        if (value is >= 0x20 and <= 0x7E)
        {
            current.Add(value);
            continue;
        }
        if (current.Count >= 3)
        {
            runs.Add(System.Text.Encoding.ASCII.GetString(current.ToArray()));
        }
        current.Clear();
    }
    if (current.Count >= 3)
    {
        runs.Add(System.Text.Encoding.ASCII.GetString(current.ToArray()));
    }
    return runs.ToArray();
}

static string MethodName(MetadataReader metadata, MethodDefinitionHandle handle)
{
    var method = metadata.GetMethodDefinition(handle);
    return $"{FullTypeName(metadata, method.GetDeclaringType())}.{metadata.GetString(method.Name)}";
}

static string FieldName(MetadataReader metadata, FieldDefinitionHandle handle)
{
    var field = metadata.GetFieldDefinition(handle);
    return $"{FullTypeName(metadata, field.GetDeclaringType())}.{metadata.GetString(field.Name)}";
}

static string MemberReferenceName(MetadataReader metadata, MemberReferenceHandle handle)
{
    var member = metadata.GetMemberReference(handle);
    return $"{ParentName(metadata, member.Parent)}.{metadata.GetString(member.Name)}";
}

static string ParentName(MetadataReader metadata, EntityHandle handle) => handle.Kind switch
{
    HandleKind.TypeDefinition => FullTypeName(metadata, (TypeDefinitionHandle)handle),
    HandleKind.TypeReference => ReferencedTypeName(metadata, (TypeReferenceHandle)handle),
    HandleKind.TypeSpecification => "TypeSpec",
    HandleKind.MethodDefinition => MethodName(metadata, (MethodDefinitionHandle)handle),
    HandleKind.ModuleReference => metadata.GetString(metadata.GetModuleReference((ModuleReferenceHandle)handle).Name),
    _ => handle.Kind.ToString(),
};

static string FullTypeName(MetadataReader metadata, TypeDefinitionHandle handle)
{
    var type = metadata.GetTypeDefinition(handle);
    var name = metadata.GetString(type.Name);
    var declaring = type.GetDeclaringType();
    if (!declaring.IsNil)
    {
        return $"{FullTypeName(metadata, declaring)}+{name}";
    }
    var ns = metadata.GetString(type.Namespace);
    return string.IsNullOrEmpty(ns) ? name : $"{ns}.{name}";
}

static string ReferencedTypeName(MetadataReader metadata, TypeReferenceHandle handle)
{
    var type = metadata.GetTypeReference(handle);
    var name = metadata.GetString(type.Name);
    var ns = metadata.GetString(type.Namespace);
    return string.IsNullOrEmpty(ns) ? name : $"{ns}.{name}";
}

static int ReadInt32(byte[] bytes, ref int offset)
{
    var value = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(offset, 4));
    offset += 4;
    return value;
}

static long ReadInt64(byte[] bytes, ref int offset)
{
    var value = BinaryPrimitives.ReadInt64LittleEndian(bytes.AsSpan(offset, 8));
    offset += 8;
    return value;
}

static ushort ReadUInt16(byte[] bytes, ref int offset)
{
    var value = BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(offset, 2));
    offset += 2;
    return value;
}

sealed record AssemblyIdentityValue(
    string Name,
    string Version,
    string Culture,
    string PublicKeyToken);

sealed record AssemblyReferenceValue(
    AssemblyIdentityValue Identity,
    string Flags,
    string HashValue);

sealed record ResolvedAssemblyValue(
    string Path,
    string RelativePath,
    string Sha256,
    string ModuleName,
    string ModuleMvid,
    AssemblyIdentityValue Identity,
    string Flags);

sealed record ConsumerMemberValue(
    string MemberKind,
    bool IsStatic,
    int MetadataToken,
    string SignatureBlob,
    TypeShape ReceiverType);

readonly record struct GenericContextValue(ImmutableArray<TypeShape> TypeArguments)
{
    public static GenericContextValue Empty =>
        new(ImmutableArray<TypeShape>.Empty);
}

sealed record TypeShape(
    string Kind,
    string DisplayName,
    string DefinitionName,
    EntityHandle DefinitionHandle,
    ImmutableArray<TypeShape> TypeArguments,
    int? ClosedFromTypeParameterIndex = null);

sealed class ExactTypeShapeProvider :
    ISignatureTypeProvider<TypeShape, GenericContextValue>
{
    public TypeShape GetArrayType(TypeShape elementType, ArrayShape shape) =>
        Simple("array", $"{elementType.DisplayName}[{new string(',', shape.Rank - 1)}]");

    public TypeShape GetByReferenceType(TypeShape elementType) =>
        Simple("by_reference", $"{elementType.DisplayName}&");

    public TypeShape GetFunctionPointerType(MethodSignature<TypeShape> signature) =>
        Simple("function_pointer", "method");

    public TypeShape GetGenericInstantiation(
        TypeShape genericType,
        ImmutableArray<TypeShape> typeArguments) =>
        new(
            "generic_instance",
            $"{genericType.DefinitionName}<{string.Join(",", typeArguments.Select(
                item => item.DisplayName))}>",
            genericType.DefinitionName,
            genericType.DefinitionHandle,
            typeArguments);

    public TypeShape GetGenericMethodParameter(
        GenericContextValue genericContext,
        int index) =>
        Simple("generic_method_parameter", $"!!{index}");

    public TypeShape GetGenericTypeParameter(
        GenericContextValue genericContext,
        int index)
    {
        if (index < 0 || index >= genericContext.TypeArguments.Length)
        {
            return Simple("generic_type_parameter", $"!{index}");
        }
        return genericContext.TypeArguments[index] with
        {
            ClosedFromTypeParameterIndex = index,
        };
    }

    public TypeShape GetModifiedType(
        TypeShape modifier,
        TypeShape unmodifiedType,
        bool isRequired) =>
        unmodifiedType;

    public TypeShape GetPinnedType(TypeShape elementType) =>
        Simple("pinned", elementType.DisplayName);

    public TypeShape GetPointerType(TypeShape elementType) =>
        Simple("pointer", $"{elementType.DisplayName}*");

    public TypeShape GetPrimitiveType(PrimitiveTypeCode typeCode) =>
        Simple(
            "primitive",
            typeCode switch
            {
                PrimitiveTypeCode.Boolean => "System.Boolean",
                PrimitiveTypeCode.Byte => "System.Byte",
                PrimitiveTypeCode.Char => "System.Char",
                PrimitiveTypeCode.Double => "System.Double",
                PrimitiveTypeCode.Int16 => "System.Int16",
                PrimitiveTypeCode.Int32 => "System.Int32",
                PrimitiveTypeCode.Int64 => "System.Int64",
                PrimitiveTypeCode.IntPtr => "System.IntPtr",
                PrimitiveTypeCode.Object => "System.Object",
                PrimitiveTypeCode.SByte => "System.SByte",
                PrimitiveTypeCode.Single => "System.Single",
                PrimitiveTypeCode.String => "System.String",
                PrimitiveTypeCode.TypedReference => "System.TypedReference",
                PrimitiveTypeCode.UInt16 => "System.UInt16",
                PrimitiveTypeCode.UInt32 => "System.UInt32",
                PrimitiveTypeCode.UInt64 => "System.UInt64",
                PrimitiveTypeCode.UIntPtr => "System.UIntPtr",
                PrimitiveTypeCode.Void => "System.Void",
                _ => typeCode.ToString(),
            });

    public TypeShape GetSZArrayType(TypeShape elementType) =>
        Simple("sz_array", $"{elementType.DisplayName}[]");

    public TypeShape GetTypeFromDefinition(
        MetadataReader reader,
        TypeDefinitionHandle handle,
        byte rawTypeKind)
    {
        var name = DefinitionName(reader, handle);
        return Named(name, handle);
    }

    public TypeShape GetTypeFromReference(
        MetadataReader reader,
        TypeReferenceHandle handle,
        byte rawTypeKind)
    {
        var name = ReferenceName(reader, handle);
        return Named(name, handle);
    }

    public TypeShape GetTypeFromSpecification(
        MetadataReader reader,
        GenericContextValue genericContext,
        TypeSpecificationHandle handle,
        byte rawTypeKind) =>
        reader.GetTypeSpecification(handle).DecodeSignature(this, genericContext);

    private static TypeShape Named(string name, EntityHandle handle) =>
        new(
            "named",
            name,
            name,
            handle,
            ImmutableArray<TypeShape>.Empty);

    private static TypeShape Simple(string kind, string displayName) =>
        new(
            kind,
            displayName,
            displayName,
            default,
            ImmutableArray<TypeShape>.Empty);

    private static string DefinitionName(
        MetadataReader reader,
        TypeDefinitionHandle handle)
    {
        var type = reader.GetTypeDefinition(handle);
        var name = reader.GetString(type.Name);
        var declaring = type.GetDeclaringType();
        if (!declaring.IsNil)
        {
            return $"{DefinitionName(reader, declaring)}+{name}";
        }
        var ns = reader.GetString(type.Namespace);
        return string.IsNullOrEmpty(ns) ? name : $"{ns}.{name}";
    }

    private static string ReferenceName(
        MetadataReader reader,
        TypeReferenceHandle handle)
    {
        var type = reader.GetTypeReference(handle);
        var name = reader.GetString(type.Name);
        var ns = reader.GetString(type.Namespace);
        return string.IsNullOrEmpty(ns) ? name : $"{ns}.{name}";
    }
}
