"""Fixed-purpose PDF text parser; stdin bytes, stdout JSON, no agent code."""
import io
import json
import os
import sys

MAX_BYTES = 8_000_000
MAX_PAGES = 500
MAX_CHARS = 1_000_000
MEMORY_BYTES = 512 * 1024 * 1024
_job = None


def limit_memory():
    global _job
    if os.name != 'nt':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        return
    import ctypes as c
    from ctypes import wintypes as w

    class Basic(c.Structure):
        _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                    ('min_working', c.c_size_t), ('max_working', c.c_size_t), ('active', w.DWORD),
                    ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]

    class IO(c.Structure):
        _fields_ = [(name, c.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

    class Extended(c.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', c.c_size_t),
                    ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]

    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    _job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.process_memory = MEMORY_BYTES
    if (not _job or not kernel.SetInformationJobObject(_job, 9, c.byref(limits), c.sizeof(limits))
            or not kernel.AssignProcessToJobObject(_job, kernel.GetCurrentProcess())):
        raise RuntimeError('PDF_RESOURCE_ISOLATION_UNAVAILABLE')


def parse(data):
    import pypdf
    if not data.startswith(b'%PDF-'):
        return {'error': 'PDF_INVALID_HEADER'}
    if len(data) > MAX_BYTES:
        return {'error': 'PDF_BYTE_LIMIT'}
    reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        return {'error': 'PDF_ENCRYPTED'}
    if len(reader.pages) > MAX_PAGES:
        return {'error': 'PDF_PAGE_LIMIT'}
    pages, count = [], 0
    for page in reader.pages:
        text = (page.extract_text() or '').replace('\x00', '')
        count += len(text)
        if count > MAX_CHARS:
            return {'error': 'PDF_TEXT_LIMIT'}
        pages.append(text)
    if not any(text.strip() for text in pages):
        return {'error': 'PDF_NO_TEXT_OCR_REQUIRED'}
    return {'pages': pages, 'parser': 'pypdf', 'parser_version': pypdf.__version__}


def main():
    try:
        limit_memory()
        result = parse(sys.stdin.buffer.read(MAX_BYTES + 1))
    except ImportError:
        result = {'error': 'PDF_DEPENDENCY_MISSING'}
    except MemoryError:
        result = {'error': 'PDF_MEMORY_LIMIT'}
    except RuntimeError as error:
        result = {'error': 'PDF_RESOURCE_ISOLATION_UNAVAILABLE' if str(error) == 'PDF_RESOURCE_ISOLATION_UNAVAILABLE' else 'PDF_PARSE_FAILED'}
    except Exception:
        result = {'error': 'PDF_PARSE_FAILED'}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    main()
