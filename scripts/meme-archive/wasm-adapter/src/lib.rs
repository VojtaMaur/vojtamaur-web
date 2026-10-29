//! Small, single-threaded WebAssembly ABI over the unmodified RFC 6330 crate.
//! The JavaScript boundary validates untrusted OTI and packet lengths before use.
use std::cell::RefCell;
use raptorq::{Decoder, Encoder, EncodingPacket, ObjectTransmissionInformation};

thread_local! {
    static ENCODER: RefCell<Option<Encoder>> = const { RefCell::new(None) };
    static DECODER: RefCell<Option<Decoder>> = const { RefCell::new(None) };
    static OUTPUT: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
}

fn output(data: Vec<u8>) { OUTPUT.with(|v| *v.borrow_mut() = data); }

#[unsafe(no_mangle)]
pub extern "C" fn alloc(len: usize) -> *mut u8 {
    Box::into_raw(vec![0u8; len].into_boxed_slice()) as *mut u8
}

/// # Safety
/// The pointer/length must describe exactly an allocation returned by alloc.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn dealloc(ptr: *mut u8, len: usize) {
    drop(unsafe { Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len)) });
}

#[unsafe(no_mangle)]
pub extern "C" fn output_ptr() -> *const u8 {
    OUTPUT.with(|v| v.borrow().as_ptr())
}

#[unsafe(no_mangle)]
pub extern "C" fn output_len() -> usize {
    OUTPUT.with(|v| v.borrow().len())
}

/// # Safety
/// The pointer/length must refer to an allocated region of WASM memory.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn init_encoder(ptr: *const u8, len: usize, symbol_size: u32, blocks: u32) {
    let data = unsafe { std::slice::from_raw_parts(ptr, len) };
    let config = ObjectTransmissionInformation::new(len as u64, symbol_size as u16, blocks as u8, 1, 1);
    let encoder = Encoder::new(data, config);
    output(config.serialize().to_vec());
    ENCODER.with(|v| *v.borrow_mut() = Some(encoder));
}

#[unsafe(no_mangle)]
pub extern "C" fn packet(block: u32, esi: u32, source_count: u32) {
    ENCODER.with(|v| {
        let enc = v.borrow();
        let block = &enc.as_ref().expect("encoder initialized").get_block_encoders()[block as usize];
        let packet = if esi < source_count {
            block.source_packets().swap_remove(esi as usize)
        } else {
            block.repair_packets(esi - source_count, 1).remove(0)
        };
        output(packet.serialize());
    });
}

/// # Safety
/// ptr must refer to exactly 12 initialized OTI bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn init_decoder(ptr: *const u8) {
    let oti: [u8;12] = unsafe { std::slice::from_raw_parts(ptr, 12) }.try_into().unwrap();
    DECODER.with(|v| *v.borrow_mut() = Some(Decoder::new(ObjectTransmissionInformation::deserialize(&oti))));
    output(Vec::new());
}

/// # Safety
/// The pointer/length must refer to one complete validated encoding packet.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn decode(ptr: *const u8, len: usize) -> u32 {
    let bytes = unsafe { std::slice::from_raw_parts(ptr, len) };
    let result = DECODER.with(|v| v.borrow_mut().as_mut().expect("decoder initialized").decode(EncodingPacket::deserialize(bytes)));
    if let Some(bytes) = result { output(bytes); 1 } else { output(Vec::new()); 0 }
}
