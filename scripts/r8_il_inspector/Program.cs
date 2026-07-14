using System.Buffers.Binary;
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
