Rails.application.routes.draw do
  resources :invoices do
    member do
      post :publish
    end
  end
  # resources :archived, only: :index
end
