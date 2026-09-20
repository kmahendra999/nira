//! MemoryBackend trait for all storage backends.

use nira_core::{NiraError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, NiraError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, NiraError>;
    fn delete(&self, doc_id: &str) -> Result<bool, NiraError>;
    fn clear(&self) -> Result<(), NiraError>;
    fn count(&self) -> Result<usize, NiraError>;
}
