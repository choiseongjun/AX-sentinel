from unittest.mock import Mock, patch

from shared.rag import LocalRetriever


def test_local_retriever_ranks_matching_documents() -> None:
    repository = Mock()
    repository.list.return_value = [
        {
            "id": "manual-1",
            "filename": "bearing-manual.md",
            "s3_key": "documents/manual-1/bearing-manual.md",
            "search_text": "베어링 온도 상승 시 윤활 상태를 점검한다.",
        },
        {
            "id": "manual-2",
            "filename": "motor-manual.md",
            "s3_key": "documents/manual-2/motor-manual.md",
            "search_text": "모터 전압을 점검한다.",
        },
    ]

    with patch("shared.rag.get_repository", return_value=repository):
        results = LocalRetriever().retrieve("베어링 온도", limit=1)

    assert len(results) == 1
    assert results[0].document_id == "manual-1"
