ActiveRecord::Schema[8.1].define(version: 2026_09_01_000000) do
  create_table "accounts", force: :cascade do |t|
    t.string "name", null: false
    t.datetime "created_at", null: false
    t.datetime "updated_at", null: false
  end

  create_table "comments", force: :cascade do |t|
    t.bigint "commentable_id", null: false
    t.string "commentable_type", null: false
    t.bigint "author_id", null: false
    t.text "body"
    t.index ["commentable_type", "commentable_id"], name: "index_comments_on_commentable"
  end

  create_table "invoices", force: :cascade do |t|
    t.bigint "account_id", null: false
    t.bigint "customer_id", null: false
    t.string "number", null: false
    t.string "status", default: "draft", null: false
    t.index ["account_id", "status"], name: "index_invoices_on_account_id_and_status"
  end

  add_foreign_key "invoices", "accounts"
end
