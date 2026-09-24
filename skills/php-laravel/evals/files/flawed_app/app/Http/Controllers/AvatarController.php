<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;

class AvatarController extends Controller
{
    public function store(Request $request)
    {
        $file = $request->file('avatar');
        $path = $file->storeAs('avatars', $file->getClientOriginalName(), 'public');

        $request->user()->update(['avatar_path' => $path]);

        return back();
    }
}
